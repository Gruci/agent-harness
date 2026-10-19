"""Bounded authenticated HTTP transport for a single repository's transactional team store."""

from __future__ import annotations

import hmac
import json
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kernel.team_client import (INTEGRATION_OPERATIONS, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES,
                                OPERATIONS, credential, decode_object, loopback)
from kernel.team_store import Store, TeamError

MAX_CONNECTIONS = 32
REQUEST_TIMEOUT = 10


@dataclass(frozen=True)
class Credential:
    actor: str
    token: str = field(repr=False)
    privileged: bool = False


def _credentials(config: dict) -> tuple[Credential, ...]:
    actors = config.get("actors")
    if not isinstance(actors, dict) or not actors or len(actors) > 256:
        raise TeamError("Server configuration requires between one and 256 actors", 400)
    found: list[Credential] = []
    seen: set[str] = set()
    for actor, settings in actors.items():
        if (not isinstance(actor, str) or not actor or len(actor) > 128
                or any(ord(char) < 33 for char in actor) or not isinstance(settings, dict)):
            raise TeamError("Invalid server actor configuration", 400)
        if set(settings) != {"token_env", "role"} or settings.get("role") not in ("worker", "integration"):
            raise TeamError("Every actor requires token_env and a worker or integration role", 400)
        token = credential(settings.get("token_env"))
        if token in seen:
            raise TeamError("Every actor, including integration actors, requires a distinct credential", 400)
        seen.add(token)
        found.append(Credential(actor, token, settings["role"] == "integration"))
    return tuple(found)


class TeamServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = MAX_CONNECTIONS

    def __init__(self, address: tuple[str, int], store: Store, repository: str,
                 actors: tuple[Credential, ...]) -> None:
        self.store, self.repository, self.actors = store, repository, actors
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, RequestHandler)

    def process_request(self, request: socket.socket, client_address: tuple) -> None:
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: tuple) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request: socket.socket, client_address: tuple) -> None:
        pass  # Never log bearer headers or malformed client input in network exception diagnostics.


class RequestHandler(BaseHTTPRequestHandler):
    server: TeamServer
    server_version = "HarnessCoordinator/1"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(REQUEST_TIMEOUT)

    def log_message(self, format: str, *args: object) -> None:
        pass  # Access logs can include adversarial URLs; tokens must never enter diagnostics.

    def _reply(self, status: int, value: dict) -> None:
        body = json.dumps(value, allow_nan=False, ensure_ascii=True).encode("utf-8")
        if len(body) > MAX_RESPONSE_BYTES:
            status, body = 503, b'{"error":"Coordinator response is too large; narrow the query","status":503}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True
        if status >= 400:
            self._close_error_response()

    def _close_error_response(self) -> None:
        """Deliver the error before closing unread input, which otherwise resets Windows TCP sockets."""
        try:
            self.connection.shutdown(socket.SHUT_WR)
            self.connection.settimeout(0.05)
            remaining = MAX_REQUEST_BYTES + 1
            deadline = time.monotonic() + 0.2
            while remaining and time.monotonic() < deadline:
                block = self.rfile.read1(min(8192, remaining))
                if not block:
                    break
                remaining -= len(block)
        except OSError:
            pass  # The response was already sent; peer disconnects do not change the verdict.

    def do_POST(self) -> None:
        try:
            if self.path != "/v1/request":
                raise TeamError("Coordinator endpoint not found", 404)
            identity = self._authenticate()
            operation, payload = self._read_request()
            if operation in INTEGRATION_OPERATIONS and not identity.privileged:
                raise TeamError("This operation requires an integration credential", 403)
            result = self.server.store.request(identity.actor, operation, payload, privileged=identity.privileged)
            self._reply(200, result)
        except TeamError as error:
            status = error.status if isinstance(error.status, int) and 400 <= error.status <= 599 else 500
            self._reply(status, {"error": str(error), "status": status})
        except (TimeoutError, UnicodeError, ValueError, RecursionError):
            self._reply(400, {"error": "Invalid or incomplete coordinator request", "status": 400})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            self._reply(500, {"error": "Coordinator could not complete the request", "status": 500})

    def do_GET(self) -> None:
        self._reply(405, {"error": "Use POST /v1/request", "status": 405})

    def _authenticate(self) -> Credential:
        headers = self.headers.get_all("Authorization", [])
        bearer = headers[0] if len(headers) == 1 else ""
        if not bearer.startswith("Bearer ") or not 32 <= len(bearer[7:]) <= 512:
            raise TeamError("Coordinator authentication required", 401)
        token = bearer[7:].encode("utf-8")
        identity = None
        for candidate in self.server.actors:
            if hmac.compare_digest(token, candidate.token.encode("utf-8")):
                identity = candidate
        if identity is None:
            raise TeamError("Coordinator authentication failed", 401)
        return identity

    def _read_request(self) -> tuple[str, dict]:
        if self.headers.get_all("Transfer-Encoding"):
            raise TeamError("Transfer-Encoding is not accepted", 400)
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
            raise TeamError("One valid Content-Length is required", 400)
        length = int(lengths[0])
        if length > MAX_REQUEST_BYTES:
            raise TeamError("Coordinator request is too large", 413)
        media = self.headers.get_all("Content-Type", [])
        if len(media) != 1 or media[0].split(";", 1)[0].strip().lower() != "application/json":
            raise TeamError("Coordinator requests require application/json", 415)
        body = self.rfile.read(length)
        if len(body) != length:
            raise TeamError("Incomplete coordinator request body", 400)
        request = decode_object(body)
        if set(request) != {"operation", "payload"}:
            raise TeamError("Coordinator envelope requires only operation and payload", 400)
        operation, payload = request["operation"], request["payload"]
        if not isinstance(operation, str) or operation not in OPERATIONS or not isinstance(payload, dict):
            raise TeamError("Unknown coordinator operation or invalid payload", 400)
        if {"actor", "owner", "privileged"}.intersection(payload):
            raise TeamError("Coordinator identity is determined by its bearer credential", 400)
        if payload.get("repository") != self.server.repository:
            raise TeamError("Coordinator repository mismatch", 409)
        return operation, payload


def make_server(store: Store, config: dict, host: str = "127.0.0.1", port: int = 0) -> TeamServer:
    """Bind locally by default; remote binds require explicit TLS or a trusted TLS reverse proxy."""
    if not isinstance(config, dict):
        raise TeamError("Server configuration must be an object", 400)
    repository = config.get("repository")
    if not isinstance(repository, str) or not repository.strip() or len(repository) > 200:
        raise TeamError("Server configuration requires a repository identifier", 400)
    tls = config.get("tls")
    proxy = config.get("reverse_proxy", False)
    if not isinstance(proxy, bool):
        raise TeamError("reverse_proxy must explicitly be true or false", 400)
    if not isinstance(host, str) or not host or not loopback(host) and not tls and not proxy:
        raise TeamError("Non-loopback binds require TLS or explicit reverse_proxy configuration", 400)
    actors = _credentials(config)
    context = None
    if tls is not None:
        if not isinstance(tls, dict) or set(tls) != {"certfile", "keyfile"}:
            raise TeamError("TLS requires certfile and keyfile", 400)
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(tls["certfile"], tls["keyfile"])
        except (OSError, ValueError, TypeError):
            raise TeamError("Could not load coordinator TLS certificate and private key", 400) from None
    server = TeamServer((host, port), store, repository, actors)
    if context is not None:
        try:
            server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
        except Exception:
            server.server_close()
            raise
    return server
