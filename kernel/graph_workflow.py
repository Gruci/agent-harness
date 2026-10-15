"""Durable architecture proposals; notifications are instructions for any AI client."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from kernel import component_graph, graph_approval

DIRECTORY = "docs/architecture/proposals"
RECEIPT = "docs/architecture/components.approval.json"


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".graph-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def current_hash(root: Path) -> str:
    path = root / component_graph.GRAPH_PATH
    return component_graph.digest(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else "absent"


def _proposal_path(root: Path, identifier: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", identifier):
        raise ValueError("invalid proposal id")
    return root / DIRECTORY / (identifier + ".json")


def _identity(base: str, target: str) -> str:
    """Content-only identity. A checkout path must not enter it — moving or re-cloning the
    repository would otherwise invalidate every recorded user decision."""
    return hashlib.sha256("\n".join((base, target)).encode()).hexdigest()


def read(root: Path, identifier: str) -> dict:
    proposal = json.loads(_proposal_path(root, identifier).read_text(encoding="utf-8"))
    if proposal["id"] != identifier:
        raise ValueError("proposal identity mismatch")
    if component_graph.digest(proposal["candidate"]) != proposal["proposed_graph_hash"]:
        raise ValueError("proposal changed after presentation; propose again")
    if _identity(proposal["base_graph_hash"], proposal["proposed_graph_hash"]) != identifier:
        raise ValueError("proposal base changed; propose again")
    return proposal


def propose(root: Path, candidate: dict, rationale: str, task_id: str) -> dict:
    """Persist the same change once, including rejected/deferred decisions."""
    errors = component_graph.validate(candidate)
    if errors:
        raise ValueError("; ".join(errors))
    if not rationale.strip():
        raise ValueError("a concrete rationale is required")
    base, target = current_hash(root), component_graph.digest(candidate)
    identifier = _identity(base, target)
    path = _proposal_path(root, identifier)
    if path.exists():
        return read(root, identifier)
    proposal = {"id": identifier, "base_graph_hash": base,
                "proposed_graph_hash": target, "candidate": candidate, "rationale": rationale,
                "task_id": task_id, "state": "awaiting_user", "notification": "queued"}
    _write(path, proposal)
    return proposal


def pending(root: Path) -> list[dict]:
    """Read pending decisions without altering repository state."""
    return [proposal for path in sorted((root / DIRECTORY).glob("*.json"))
            if (proposal := read(root, path.stem))["state"] in ("awaiting_user", "approved")]


def notify(root: Path, identifier: str) -> dict:
    """Return an agent-facing request; stdout alone is not proof of user display."""
    proposal = read(root, identifier)
    return {"type": "needs_decision", "id": identifier, "rationale": proposal["rationale"],
            "proposal": f"{DIRECTORY}/{identifier}.json",
            "action": "Show the classification and graph delta to the user; ask approve, revise or defer."}


def decide(root: Path, identifier: str, choice: str, response: str, conversation_ref: str) -> dict:
    """Record the actual user response; this function does not ask on their behalf."""
    proposal = read(root, identifier)
    record = {key: proposal[key] for key in ("base_graph_hash", "proposed_graph_hash")}
    record.update(proposal_id=identifier, actor="user", choice=choice,
                  response=response, conversation_ref=conversation_ref)
    errors = graph_approval.validate(record, proposal)
    if errors:
        raise ValueError("; ".join(errors))
    if current_hash(root) != proposal["base_graph_hash"]:
        raise ValueError("stale proposal: graph changed; rebase and ask about the new delta")
    if proposal.get("decision") and proposal["decision"] != record:
        raise ValueError("decision already recorded; create a revised proposal")
    proposal.update(decision=record, notification="delivered",
                    state={"approve": "approved", "reject": "rejected", "defer": "deferred"}[choice])
    _write(_proposal_path(root, identifier), proposal)
    return proposal


def apply(root: Path, identifier: str) -> None:
    """Apply only the reviewed delta, with an exclusive transaction and stale-base check."""
    lock = root / DIRECTORY / ".apply.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("x", encoding="utf-8"):
        pass
    try:
        _apply_locked(root, identifier)
    finally:
        lock.unlink(missing_ok=True)


def _apply_locked(root: Path, identifier: str) -> None:
    proposal = read(root, identifier)
    record = proposal.get("decision", {})
    errors = graph_approval.validate(record, proposal)
    if errors or record.get("choice") != "approve":
        raise ValueError("user decision required: " + "; ".join(errors))
    if current_hash(root) not in (proposal["base_graph_hash"], proposal["proposed_graph_hash"]):
        raise ValueError("stale proposal; canonical graph has changed")
    errors = component_graph.validate(proposal["candidate"])
    if errors:
        raise ValueError("; ".join(errors))
    _write(root / component_graph.GRAPH_PATH, proposal["candidate"])
    _write(root / RECEIPT, {"proposal_id": identifier})
    proposal["state"] = "applied"
    _write(_proposal_path(root, identifier), proposal)


def bind_candidate(graph: dict, syntax: str, patterns: list[str]) -> dict:
    """The same graph with only its technology rebound; approved components and edges stay as decided."""
    candidate = json.loads(json.dumps(graph))
    candidate["technology"] = {**candidate["technology"], "syntax": syntax, "sources": list(patterns)}
    return candidate


def bind(root: Path, syntax: str, patterns: list[str], response: str, conversation_ref: str, task_id: str) -> dict:
    """Record the stack answer the user already gave as the binding decision, without asking again."""
    graph = component_graph.load(root)
    proposal = propose(root, bind_candidate(graph, syntax, patterns),
                       f"Bind the component graph to the chosen language: syntax {syntax}, sources {' '.join(patterns)}",
                       task_id)
    decide(root, proposal["id"], "approve", response, conversation_ref)
    apply(root, proposal["id"])
    return read(root, proposal["id"])


def starter_candidate(graph: dict, source: str, responsibility: str) -> dict:
    """첫 분류 — 코드 전체를 컴포넌트 하나(`app`, 역할 `core`)로. 영역이 둘 이상 생기면 plan 의 「분류 제안」이 나눈다.
    planned 라 코드가 없어도 있어도 오류가 아니고, 외부 의존은 `*` 로 열어 둔다 — 첫날 묻는 질문을 줄이는 것이 목적이다."""
    if graph["components"]:
        raise ValueError("starter is only for the first classification — the graph already has components")
    folder = source.strip().strip("/")
    if not folder or not component_graph.safe_relative(folder) or folder.startswith("."):
        raise ValueError("--source must be a folder inside the repo, e.g. src or app")
    candidate = json.loads(json.dumps(graph))
    candidate["categories"] = [{"id": "app", "name": "App", "roles": ["core"],
                                "description": "All product code until it is split into areas"}]
    candidate["components"] = [{"id": "app", "name": "App", "category": "app", "responsibility": responsibility,
                                "excludes": [], "root": folder, "roles": {"core": ["**"]}, "public": [],
                                "state": "planned", "external": ["*"]}]
    candidate["edges"] = []
    candidate["role_dependencies"] = {"core": ["core"]}
    return candidate


def starter(root: Path, source: str, responsibility: str, response: str, conversation_ref: str) -> dict:
    """사용자가 설정 때 한 답("무엇을 만드나"·스택 확인)을 첫 분류 결정으로 기록한다 — `bind` 와 같은 방식이다."""
    proposal = propose(root, starter_candidate(component_graph.load(root), source, responsibility),
                       f"First classification: all product code under {source} as one component until it is split",
                       "")
    decide(root, proposal["id"], "approve", response, conversation_ref)
    apply(root, proposal["id"])
    return read(root, proposal["id"])


def check_approval(root: Path, graph: dict) -> list[str]:
    """Read-only consistency check, independent of proposal status flags."""
    try:
        receipt = json.loads((root / RECEIPT).read_text(encoding="utf-8"))
        proposal = read(root, receipt["proposal_id"])
        errors = graph_approval.validate(proposal.get("decision", {}), proposal)
        if proposal.get("decision", {}).get("choice") != "approve":
            errors.append("graph has no approving user decision; needs_decision")
        if component_graph.digest(graph) != proposal["proposed_graph_hash"]:
            errors.append("canonical graph differs from the approved proposal; needs_decision")
        return errors
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"graph decision record missing or invalid: {exc}; needs_decision"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="action", required=True)
    proposed = sub.add_parser("propose")
    proposed.add_argument("candidate", type=Path)
    proposed.add_argument("--reason", required=True)
    proposed.add_argument("--task", default="")
    decision = sub.add_parser("decide")
    decision.add_argument("id")
    decision.add_argument("--choice", choices=("approve", "reject", "defer"), required=True)
    decision.add_argument("--response", required=True)
    decision.add_argument("--conversation", required=True)
    sub.add_parser("pending")
    applied = sub.add_parser("apply")
    applied.add_argument("id")
    bound = sub.add_parser("bind", help="rebind technology to the stack the user chose; records that answer")
    bound.add_argument("--syntax", required=True)
    bound.add_argument("--sources", nargs="+", required=True, metavar="PATTERN")
    bound.add_argument("--response", required=True, help="the user's stack answer, quoted")
    bound.add_argument("--conversation", required=True)
    bound.add_argument("--task", default="")
    first = sub.add_parser("starter", help="first classification: one planned component for all product code")
    first.add_argument("--source", required=True, help="product code folder, e.g. src")
    first.add_argument("--responsibility", default="Everything the product does until it is split")
    first.add_argument("--response", required=True, help="the user's setup answer, quoted")
    first.add_argument("--conversation", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "starter":
            from kernel.hook import refresh_projection   # 순환 import 회피 — hook 이 이 모듈을 부른다

            proposal = starter(args.root, args.source, args.responsibility, args.response, args.conversation)
            refresh_projection(args.root)               # 기능 지도를 바로 맞춘다 — 안 하면 설정 직후 --verify 가 지도 불일치로 실패했다
            print(f"[STARTER] all product code under {args.source} is component `app` — decision recorded in "
                  f"{DIRECTORY}/{proposal['id']}.json. Split it in a plan's classification row once a second area appears.")
        elif args.action == "propose":
            proposal = propose(args.root, json.loads(args.candidate.read_text(encoding="utf-8")), args.reason, args.task)
            print(json.dumps(notify(args.root, proposal["id"]), ensure_ascii=False))
        elif args.action == "bind":
            proposal = bind(args.root, args.syntax, args.sources, args.response, args.conversation, args.task)
            print(f"[BIND] technology bound to syntax {args.syntax} — decision recorded in {DIRECTORY}/{proposal['id']}.json")
        elif args.action == "pending":
            print(json.dumps([notify(args.root, item["id"]) for item in pending(args.root)], ensure_ascii=False))
        elif args.action == "decide":
            decide(args.root, args.id, args.choice, args.response, args.conversation)
        else:
            apply(args.root, args.id)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
