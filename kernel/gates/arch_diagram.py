"""kernel/gates/arch_diagram.py — 아키텍처 그림과 실제 코드의 1:1 대조 (검사 48).

그림 속 상자가 코드의 어디인지 증명되지 않으면 그 그림은 검증되지 않은 설명글일 뿐이다. 이
게이트는 정본 JSON 노드의 `sources` 로 경로 실존, 행 범위, 커버리지, 영수증(deliver 가 남기는
해시 기록), revision 을 확인한다. 스키마·배치·증거 판정은 엔진의 validate 에 맡긴다.
node 가 없으면 엔진에 맡긴 부분만 [TOOL] 이 되고, 이 파일의 자체 판정은 그대로 실행된다.

  자체 판정   external 아닌 노드마다 sources · 구현 컴포넌트 커버리지 · 경로·행 실존 · 영수증 해시 · revision 실존
  REPORT      revision 이후 근거 소스가 바뀐 노드 — 그림을 다시 볼 신호다. 오탐 여지가 있어 실패 건수에 넣지 않는다
  엔진 위임   validate --repo-root 의 diagnostics[] → FAIL, node 없음 → TOOL.
              영수증 해시가 현재 정본과 같으면 부르지 않는다 — deliver 가 이미 통과시킨 정본이다

전량 모드(레포 전체 검사)에서만 돈다. 검사 34·35 와 같다. 파일 하나만 보는 `--file` 에서는
그림과 소스 전체를 맞대어 볼 수 없다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from kernel import component_graph, diagram, profile
from kernel.context import READ_ENC, ROOT, tracked

Skip = tuple[str, str]
Section = tuple[str, str, list[str], "Skip | None"]

# 코드에 대응물이 없는 노드 — 사람·외부 시스템·상태기계의 추상 상태
EXEMPT_TYPES = {"external"}
EXEMPT_KINDS = {"lifecycle"}


def diagrams() -> list[Path]:
    """추적되는 정본 전부. 영수증·HTML 은 제외."""
    return [p for p in tracked("*.json", under=diagram.DIAGRAM_DIR + "/") if diagram.kind_of(p)]


def expected_nodes() -> tuple[str, ...]:
    """Implemented graph components need source coverage; planned nodes do not."""
    graph_path = ROOT / profile.COMPONENT_GRAPH
    if not graph_path.is_file():
        return ()
    try:
        graph = component_graph.load(ROOT, profile.COMPONENT_GRAPH)
    except (OSError, ValueError):
        return ()  # graph_schema reports malformed or unreadable canonical graphs.
    return tuple(sorted({"" if item["root"] == "." else item["root"].rstrip("/") + "/"
                         for item in graph["components"] if item["state"] == "implemented"}))


def _git_ok(*args: str) -> bool:
    done = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True)
    return done.returncode == 0


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding=READ_ENC, errors="replace").splitlines())


def _source_lines(rel: str, node_id: str, sources: list[object]) -> list[str]:
    """한 노드의 sources 실존·행 범위. 반환은 위반 문장."""
    found: list[str] = []
    for item in sources:
        if not isinstance(item, dict) or not item.get("path"):
            found.append(f"{rel}: 노드 {node_id} 의 sources 항목에 path 없음")
            continue
        target = ROOT / str(item["path"])
        if not target.is_file():
            found.append(f"{rel}: 노드 {node_id} → {item['path']} 실존하지 않음 — 이름을 바꿨으면 그림도 고친다")
            continue
        line, end = item.get("line"), item.get("end_line")
        last = end or line
        if isinstance(last, int) and last > _line_count(target):
            found.append(f"{rel}: 노드 {node_id} → {item['path']} 행 {last} 없음 (파일은 {_line_count(target)}줄)")
    return found


def _changed_since(revision: str) -> set[str]:
    """revision 이후 바뀐 추적 경로 전체. 예전에는 노드마다 git diff 를 불렀는데, 그 72회가 Stop 훅 21초 중
    6초를 차지해 그림당 1회로 줄였다."""
    if not revision:
        return set()
    done = subprocess.run(["git", "diff", "--name-only", revision, "HEAD"], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {line.strip() for line in done.stdout.splitlines() if line.strip()}


# `label: 샘플` source 는 데이터 예시다(dev/DIAGRAM.md). 코드 증거가 아니므로 변경 감지 대상에서 뺀다.
# 커밋마다 바뀌는 관찰 기록을 샘플로 걸어 두면 그 노드는 항상 "바뀜" 으로 보고되기 때문이다.
SAMPLE_LABEL = "샘플"


def _stale_lines(rel: str, changed: set[str], node_id: str, sources: list[object]) -> list[str]:
    """revision 이후 근거 소스가 바뀐 노드. REPORT 로만 보고한다."""
    found: list[str] = []
    for item in sources:
        if not isinstance(item, dict) or item.get("label") == SAMPLE_LABEL:
            continue
        path = str(item.get("path") or "")
        if path in changed:
            found.append(f"{rel}: 노드 {node_id} 의 근거 소스 {path} 가 revision 이후 바뀜 — 그림을 다시 확인하라")
    return found


def _check_one(source: Path) -> tuple[list[str], list[str]]:
    rel = source.relative_to(ROOT).as_posix()
    kind = diagram.kind_of(source) or ""
    doc = diagram.load(source)
    if not doc:
        return [f"{rel}: JSON 파싱 실패"], []
    hard: list[str] = []
    soft: list[str] = []
    repository = doc.get("meta", {}).get("repository") if isinstance(doc.get("meta"), dict) else None
    revision = str(repository.get("revision") or "") if isinstance(repository, dict) else ""
    if revision and not _git_ok("cat-file", "-e", f"{revision}^{{commit}}"):
        hard.append(f"{rel}: revision {revision[:7]} 이 이 레포에 없음 — deliver 를 다시 돌려 HEAD 로 찍는다")
        revision = ""                    # 없는 커밋과의 diff 는 전부 '바뀜' 이라 REPORT 가 소음이 된다
    changed = _changed_since(revision)
    covered: set[str] = set()
    for node in doc.get(diagram.NODE_KEY[kind], []) or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "?")
        sources = node.get("sources") or []
        if not sources:
            if kind not in EXEMPT_KINDS and node.get("type") not in EXEMPT_TYPES:
                hard.append(f"{rel}: 노드 {node_id} 에 sources 없음 — 코드 어디인지 적어야 그림이다")
            continue
        hard += _source_lines(rel, node_id, sources)
        soft += _stale_lines(rel, changed, node_id, sources)
        covered |= {str(item.get("path") or "") for item in sources
                    if isinstance(item, dict) and (ROOT / str(item.get("path") or "")).is_file()}
    if kind == "architecture":
        for prefix in expected_nodes():
            if not any(path.startswith(prefix) for path in covered):
                hard.append(f"{rel}: {prefix} 를 가리키는 노드 없음 — 구현된 컴포넌트의 실제 소스 근거가 필요하다")
    hard += _receipt_lines(rel, source)
    return hard, soft


def _receipt(source: Path) -> dict[str, object]:
    path = diagram.receipt_path(source)
    return diagram.load(path) if path.exists() else {}


def _receipt_fresh(source: Path) -> bool:
    """영수증이 현재 정본의 해시를 갖고 있는가.

    deliver 는 엔진이 실패하면 영수증을 쓰지 않는다. 그러니 해시가 같다는 것은 이 정본이 그 revision 의
    blob 으로 validate 를 통과했다는 뜻이다. validate 의 입력은 정본과 그 blob 뿐이라 입력이 같으면
    결과도 같다. 그래서 다시 부를 이유가 없고, 부르면 그림 한 장에 4초가 걸린다.
    """
    receipt = _receipt(source)
    return bool(receipt) and receipt.get("spec_sha256_lf") == diagram.spec_sha256_lf(source)


def _receipt_lines(rel: str, source: Path) -> list[str]:
    receipt = _receipt(source)
    if not receipt:
        return [f"{rel}: 영수증 없음 — `python -X utf8 -m kernel.diagram deliver` 로 렌더한다"]
    if receipt.get("spec_sha256_lf") != diagram.spec_sha256_lf(source):
        return [f"{rel}: 영수증 해시가 현재 정본과 다름 — 정본을 고쳤으면 다시 deliver 한다"]
    if not diagram.output_path(source).exists():
        return [f"{rel}: 렌더 HTML 없음 — deliver 산출물을 커밋한다"]
    return []


def check_arch_diagram() -> tuple[list[str], list[str]]:
    """Validate explicit renderer artifacts; the graph gate owns required feature maps."""
    found = diagrams()
    if not found:
        return [], []
    hard: list[str] = []
    soft: list[str] = []
    for source in found:
        one_hard, one_soft = _check_one(source)
        hard += one_hard
        soft += one_soft
    return hard, soft


def engine_sections() -> list[Section]:
    """그림마다 엔진 validate 에 판정을 맡긴다. 영수증 해시가 현재 정본과 같으면 다시 부르지 않고 OK 로
    둔다. 다르면 validate 를 부르고, node 가 없으면 TOOL 로 찍는다. TOOL 은 통과가 아니다."""
    sections: list[Section] = []
    for source in diagrams():
        rel = source.relative_to(ROOT).as_posix()
        slug = f"arch_diagram_engine:{source.name}"
        title = f"그림 엔진 진단({rel})"
        if _receipt_fresh(source):
            sections.append((slug, title, [], None))
            continue
        receipt = diagram.validate(diagram.kind_of(source) or "", source)
        if receipt.get("tool_missing"):
            sections.append((slug, title, [], ("TOOL", f"{receipt['tool_missing']} 없음 — node 를 설치하면 켜진다")))
            continue
        lines = [f"{rel}: {line}" for line in diagram.diagnostics_lines(receipt)]
        if not receipt.get("ok") and not lines:
            lines = [f"{rel}: 엔진 실패(진단 없음)"]
        sections.append((slug, title, lines, None))
    return sections
