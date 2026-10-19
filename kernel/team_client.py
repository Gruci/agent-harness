"""Authenticated coordinator client; credentials remain in the configured environment variable."""

from __future__ import annotations

import ipaddress
import http.client
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from kernel.team_store import OPERATIONS, PRIVILEGED as INTEGRATION_OPERATIONS, TeamError

MAX_REQUEST_BYTES = 65_536
MAX_RESPONSE_BYTES = 1_048_576
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def loopback(host: str) -> bool:
    """Only a literal loopback address or localhost permits unencrypted client traffic."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def credential(environment: str) -> str:
    """Read a bounded printable bearer credential without putting it in diagnostics."""
    if not isinstance(environment, str) or not ENV_NAME.fullmatch(environment):
        raise TeamError("Invalid coordinator credential environment name", 400)
    value = os.environ.get(environment, "")
    if not 32 <= len(value) <= 512 or any(not 33 <= ord(char) <= 126 for char in value):
        raise TeamError("Coordinator credential is missing or invalid; set the configured token environment", 401)
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite JSON number")
    return number


def decode_object(body: bytes) -> dict:
    """Reject ambiguous duplicate keys, nonobjects and nonfinite JSON numbers."""
    def reject_constant(_value: str) -> None:  # closure-ok: json's constant callback receives only the token
        raise ValueError("nonfinite JSON number")

    parsed = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object,
                        parse_constant=reject_constant, parse_float=_finite_float)
    if not isinstance(parsed, dict):
        raise ValueError("JSON object required")
    return parsed


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: object, fp: object, code: int, msg: str,
                         headers: object, newurl: str) -> None:
        return None


class Client:
    """One repository's coordinator endpoint; every request carries that repository identity."""

    def __init__(self, config: dict) -> None:
        if not isinstance(config, dict) or not config:
            raise TeamError("Team coordination is disabled; configure TEAM first", 503)
        self.repository = config.get("repository")
        if not isinstance(self.repository, str) or not self.repository.strip() or len(self.repository) > 200:
            raise TeamError("TEAM requires a repository identifier", 400)
        self.url = self._endpoint(config.get("url"))
        self.token_env = config.get("token_env")
        if not isinstance(self.token_env, str) or not ENV_NAME.fullmatch(self.token_env):
            raise TeamError("TEAM requires a credential environment name", 400)
        self.timeout = config.get("timeout", 15)
        if (isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float))
                or not math.isfinite(self.timeout) or not 0 < self.timeout <= 120):
            raise TeamError("Coordinator timeout must be greater than zero and at most 120 seconds", 400)
        self._opener = urllib.request.build_opener(_NoRedirect())

    @staticmethod
    def _endpoint(url: object) -> str:
        if not isinstance(url, str) or not url or len(url) > 2048 or any(ord(char) < 33 for char in url):
            raise TeamError("Invalid TEAM coordinator URL", 400)
        try:
            parts = urllib.parse.urlsplit(url)
            hostname, _port = parts.hostname, parts.port
        except ValueError:
            raise TeamError("Invalid TEAM coordinator URL", 400) from None
        if (parts.scheme not in ("http", "https") or not hostname or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment):
            raise TeamError("Coordinator URL must use HTTP(S) without credentials, query or fragment", 400)
        if parts.scheme == "http" and not loopback(hostname):
            raise TeamError("Remote coordinator connections require HTTPS", 400)
        return url.rstrip("/") + "/v1/request"

    def request(self, operation: str, payload: dict) -> dict:
        if not isinstance(operation, str) or operation not in OPERATIONS or not isinstance(payload, dict):
            raise TeamError("Unknown coordinator operation or invalid payload", 400)
        if payload.get("repository", self.repository) != self.repository:
            raise TeamError("Coordinator repository mismatch", 409)
        supplied = {**payload, "repository": self.repository}
        try:
            body = json.dumps({"operation": operation, "payload": supplied}, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            raise TeamError("Coordinator payload must contain JSON values", 400) from None
        if len(body) > MAX_REQUEST_BYTES:
            raise TeamError("Coordinator request is too large", 413)
        request = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Authorization": "Bearer " + credential(self.token_env), "Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return self._response(response.read(MAX_RESPONSE_BYTES + 1), response.status)
        except urllib.error.HTTPError as error:
            try:
                response_body = error.read(MAX_RESPONSE_BYTES + 1)
            finally:
                error.close()
            return self._response(response_body, error.code)
        except (OSError, urllib.error.URLError, ValueError, http.client.HTTPException):
            raise TeamError("Coordinator connection failed; check its availability and TLS configuration", 503) from None

    @staticmethod
    def _response(body: bytes, status: int) -> dict:
        if len(body) > MAX_RESPONSE_BYTES:
            raise TeamError("Coordinator response exceeded its size limit", 502)
        try:
            result = decode_object(body)
        except (ValueError, UnicodeError, RecursionError):
            raise TeamError("Coordinator returned an invalid response", 502) from None
        if status != 200:
            message = result.get("error")
            raise TeamError(message if isinstance(message, str) else "Coordinator rejected the request", status)
        return result
