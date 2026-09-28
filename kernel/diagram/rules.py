"""kernel/diagram/rules.py — 훅별 규칙 지도를 배선에서 생성한다. 손으로 그리지 않는다.

"어느 훅이 언제 무엇을 검사하나"는 이미 코드에 있다 — `.claude/settings.json` 의 배선, 훅 파일의
첫 docstring, 러너의 게이트 목록. 그걸 손으로 옮겨 그리면 훅 하나 늘 때마다 그림이 낡는다.
그래서 여기서 workflow 정본을 만들고, deliver 가 렌더하고, 아키텍처 그림 1:1 대조(검사 48)가 실물과 맞춰 본다.

  레인 = 훅 이벤트(세션 시작 → 프롬프트 → 툴 전 → 저장 후 → 에이전트 반환 → 종료)
  노드 = 훅 하나. `sys.exit(2)` 를 가진 훅은 security(차단 가능), 인라인 셸은 frontend(경고 문자열만 냄)
  소스 = 훅 파일 자체. 노드 하나에 파일 하나가 대응한다
  카드 = 이벤트별 "훅: 무엇을 검사" 와 러너 게이트 48종 제목
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import re
import subprocess
from pathlib import Path

from kernel import runner
from kernel.context import READ_ENC, ROOT

SETTINGS = ROOT / ".claude" / "settings.json"
OUTPUT = ROOT / "docs" / "architecture" / "rules.workflow.json"
MAX_COL = 5                                  # workflow v2 의 col 상한. 넘치면 "(계속)" 레인을 새로 연다
EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStop", "Stop")
LANE_LABEL = {
    "SessionStart": "세션 시작", "UserPromptSubmit": "프롬프트", "PreToolUse": "툴 실행 전",
    "PostToolUse": "저장 직후", "SubagentStop": "에이전트 반환", "Stop": "세션 종료",
}
DOT = {"SessionStart": "cyan", "UserPromptSubmit": "slate", "PreToolUse": "amber",
       "PostToolUse": "emerald", "SubagentStop": "violet", "Stop": "rose"}
_HOOK_FILE = re.compile(r"\.claude/(?:hooks|skills)/[\w./-]+\.(?:py|md|mjs)")
_INLINE_TAG = re.compile(r"\[([A-Z ]+)\]")


def _entries() -> list[tuple[str, str, str]]:
    """(이벤트, matcher, command) — settings.json 순서 그대로. 순서가 곧 실행 순서다."""
    raw = json.loads(SETTINGS.read_text(encoding=READ_ENC))
    found: list[tuple[str, str, str]] = []
    for event in EVENTS:
        for group in raw.get("hooks", {}).get(event, []):
            for hook in group.get("hooks", []):
                found.append((event, group.get("matcher") or "", hook.get("command") or ""))
    return found


def _doc_line(path: Path) -> str:
    """훅이 스스로 말하는 한 줄 — 파이썬은 docstring 첫 줄, MD 는 첫 제목, 그 외는 파일명."""
    text = path.read_text(encoding=READ_ENC, errors="replace")
    if path.suffix == ".py":
        try:
            doc = ast.get_docstring(ast.parse(text)) or ""
        except SyntaxError:
            doc = ""
        return doc.splitlines()[0].strip() if doc else path.name
    if path.suffix == ".md":
        for line in text.splitlines():
            if line.startswith("#"):
                return line.lstrip("# ").strip()
    return path.name


def _node(event: str, index: int, matcher: str, command: str) -> tuple[dict[str, object], str]:
    """(노드, 카드 항목). 인라인 셸은 settings.json 자체가 소스다."""
    match = _HOOK_FILE.search(command)
    if match and (ROOT / match.group(0)).is_file():
        path = ROOT / match.group(0)
        stem = path.stem.removeprefix("check_")
        blocks = "sys.exit(2)" in path.read_text(encoding=READ_ENC, errors="replace")
        kind = "security" if blocks else "backend"
        label, note = stem, _doc_line(path)
        sources = [{"path": match.group(0), "label": "훅"}]
    else:
        tags = _INLINE_TAG.findall(command)
        label = (tags[0].title().replace(" ", "") if tags else f"inline{index}").lower()
        kind, note = "frontend", "인라인 셸 — 경고 문자열만 낸다: " + " · ".join(tags or ["점검"])
        sources = [{"path": ".claude/settings.json", "label": "인라인 배선"}]
    node_id = re.sub(r"[^A-Za-z0-9_-]", "-", f"{event.lower()}-{label}")
    node: dict[str, object] = {
        "id": node_id, "lane": event.lower(), "col": index % (MAX_COL + 1), "type": kind,
        "label": label, "sublabel": (matcher or "항상")[:28], "width": 140, "sources": sources,
    }
    return node, f"{label}: {note}"


def _gate_cards() -> list[dict[str, object]]:
    """러너가 실제로 돌리는 게이트 제목 — 12개씩 카드로 나눈다."""
    files, ui_files = runner.source_files()
    with contextlib.redirect_stdout(io.StringIO()):          # 러너가 찍는 [REPORT] 출력은 지도 생성과 무관하니 버린다
        sections = runner._build_sections(files, ui_files, True, runner.tracked_md_files())
    titles = [f"{slug} — {title}" for slug, title, _violations, _skip in sections
              if not slug.startswith("arch_diagram_engine")]
    cards: list[dict[str, object]] = []
    for start in range(0, len(titles), 12):
        chunk = titles[start:start + 12]
        cards.append({"dot": "slate", "title": f"러너 게이트 {start + 1}~{start + len(chunk)}", "items": chunk})
    return cards


def build() -> dict[str, object]:
    lanes: list[dict[str, object]] = []
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    cards: list[dict[str, object]] = []
    first_of: list[str] = []
    by_event: dict[str, list[tuple[str, str]]] = {}
    for event, matcher, command in _entries():
        by_event.setdefault(event, []).append((matcher, command))
    for event, entries in by_event.items():
        items: list[str] = []
        previous: str | None = None
        for index, (matcher, command) in enumerate(entries):
            node, item = _node(event, index, matcher, command)
            lane_id = event.lower() + ("" if index <= MAX_COL else f"-{index // (MAX_COL + 1)}")
            node["lane"] = lane_id
            if not any(lane["id"] == lane_id for lane in lanes):
                label = LANE_LABEL[event] + (" (계속)" if lane_id != event.lower() else "")
                lanes.append({"id": lane_id, "label": label, **({"variant": "exception"} if event == "Stop" else {})})
            nodes.append(node)
            items.append(item)
            if previous:
                edges.append({"id": f"{previous}--{node['id']}", "from": previous, "to": str(node["id"])})
            elif first_of:
                edges.append({"id": f"{first_of[-1]}--{node['id']}", "from": first_of[-1], "to": str(node["id"]),
                              "label": "다음 이벤트", "variant": "emphasis"})
            if not previous:
                first_of.append(str(node["id"]))
            previous = str(node["id"])
        cards.append({"dot": DOT[event], "title": f"{LANE_LABEL[event]} — 무엇을 검사하나", "items": items})
    cards += _gate_cards()
    blocking = [str(n["id"]) for n in nodes if n["type"] == "security"]
    views = [
        {"id": "timeline", "label": "이벤트 순서", "focus": first_of, "note": "세션 시작에서 종료까지, 훅이 실행되는 이벤트 순서다."},
        {"id": "blocking", "label": "차단할 수 있는 훅", "focus": blocking, "note": "exit 2 를 낼 수 있는 훅 — 직접 관측한 위반만 여기서 막는다."},
        {"id": "stop", "label": "세션 종료 검사", "focus": [str(n["id"]) for n in nodes if str(n["lane"]).startswith("stop")],
         "note": "세션 종료 시점에 전체를 검사한다. 통과하기 전에는 세션이 끝나지 않는다."},
    ]
    return {
        "schema_version": 2, "diagram_type": "workflow",
        "meta": {
            "title": "훅별 규칙 지도 — 무엇이 언제 무엇을 검사하나",
            "quality_profile": "showcase",
            "repository": {"url": _origin(), "revision": "0" * 40},
            "views": views,
        },
        "lanes": lanes, "phases": [], "groups": [], "mainPath": first_of,
        "nodes": nodes, "edges": edges, "cards": cards,
    }


def _origin() -> str:
    done = subprocess.run(["git", "remote", "get-url", "origin"], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return done.stdout.strip().removesuffix(".git") if done.returncode == 0 else "https://example.invalid/repo"


def write() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return OUTPUT
