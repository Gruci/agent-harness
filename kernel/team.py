"""Operator and worker commands for the shared coordinator; TEAM stays disabled until configured."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kernel.team_client import Client, decode_object
from kernel.team_server import make_server
from kernel.team_store import Store, TeamError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shared team coordinator")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run the authenticated coordinator")
    serve.add_argument("--database", type=Path, required=True)
    serve.add_argument("--config", type=Path, required=True, help="Local uncommitted JSON configuration")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--lease-seconds", type=int, default=300)
    serve.add_argument("--max-active", type=int, default=16)
    for name in ("list", "status", "renew", "expand", "cancel", "withdraw"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, help="Client JSON; otherwise use harness_profile.TEAM")
        if name != "list":
            command.add_argument("task_id")
        if name in ("renew", "expand", "cancel", "withdraw"):
            command.add_argument("--epoch", type=int, required=True)
        if name == "expand":
            command.add_argument("--resources", required=True, help="JSON array of resources")
        if name == "list":
            command.add_argument("--cursor", default="")
            command.add_argument("--limit", type=int, default=50)
    local = commands.add_parser("scope", help="Operate a local task and update its fencing receipt")
    local.add_argument("scope")
    local.add_argument("operation", choices=("renew", "expand", "status", "withdraw", "cancel", "reclaim", "enqueue"))
    local.add_argument("--resources", nargs="+", default=[])
    beat = commands.add_parser("heartbeat", help="Renew a local task while its worker is active")
    beat.add_argument("--scope", required=True)
    beat.add_argument("--interval", type=float, default=30)
    beat.add_argument("--once", action="store_true")
    return parser


def _read_config(path: Path) -> dict:
    try:
        return decode_object(path.read_bytes())
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise TeamError("Could not read valid coordinator JSON configuration", 400) from None


def client_config(path: Path | None = None) -> dict:
    if path is not None:
        return _read_config(path)
    from kernel import profile

    config = getattr(profile, "TEAM", {})
    return config if isinstance(config, dict) else {}


def _serve(args: argparse.Namespace) -> int:
    config = _read_config(args.config)
    if not 0 <= args.port <= 65535 or args.lease_seconds < 1 or args.max_active < 1:
        raise TeamError("Port, lease seconds or active-task limit is invalid", 400)
    server = make_server(Store(args.database, lease_seconds=args.lease_seconds, max_active=args.max_active),
                         config, args.host, args.port)
    print(f"[TEAM] Coordinator listening on {args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] in ("check", "reconcile", "reconcile-all"):
        from kernel.team_git import main as git_main

        return git_main(raw)
    args = _parser().parse_args(raw)
    try:
        if args.command == "serve":
            return _serve(args)
        if args.command in ("scope", "heartbeat"):
            return _local(args)
        payload: dict = {}
        if args.command == "list":
            payload.update(cursor=args.cursor, limit=args.limit)
        if args.command != "list":
            payload["task_id"] = args.task_id
        if args.command in ("renew", "expand", "cancel", "withdraw"):
            payload["epoch"] = args.epoch
        if args.command == "expand":
            try:
                payload["resources"] = json.loads(args.resources)
            except ValueError:
                raise TeamError("Resources must be a JSON array", 400) from None
            if not isinstance(payload["resources"], list):
                raise TeamError("Resources must be a JSON array", 400)
        result = Client(client_config(args.config)).request(args.command, payload)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except TeamError as error:
        print(f"[TEAM] {error}", file=sys.stderr)
        return 1
    except OSError:
        print("[TEAM] Coordinator storage or socket could not be opened", file=sys.stderr)
        return 1


def _local(args: argparse.Namespace) -> int:
    from kernel import team_tasks
    from kernel.task_finish import _gh
    from kernel.workboard import board_dir

    root = board_dir().parent
    try:
        if args.command == "heartbeat":
            result = team_tasks.heartbeat(root, args.scope, args.interval, args.once)
        elif args.operation == "reclaim":
            result = team_tasks.reclaim(root, args.scope)
        elif args.operation == "withdraw":
            from kernel.team_withdraw import withdraw

            result = withdraw(root, args.scope)
        elif args.operation == "enqueue":
            receipt = team_tasks.load(root, args.scope)
            if receipt.get("state") not in ("submitted", "verified"):
                raise ValueError("Submit the frozen candidate before enqueueing it")
            done = _gh(root, "pr", "merge", receipt["branch"], "--auto", "--merge")
            if done.returncode:
                raise ValueError("GitHub did not accept the merge-queue request")
            result = {"task_id": receipt["task_id"], "state": "queue_requested"}
        else:
            extra = {"resources": args.resources} if args.operation == "expand" else {}
            result = team_tasks.refresh(root, args.scope) if args.operation == "status" else team_tasks.operation(root, args.scope, args.operation, extra)
        print(json.dumps(result, sort_keys=True))
        return 0
    except ValueError as error:
        raise TeamError(str(error), 409) from error


if __name__ == "__main__":
    sys.exit(main())
