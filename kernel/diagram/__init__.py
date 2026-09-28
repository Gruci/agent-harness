"""kernel/diagram — 다이어그램 엔진을 호출하는 모듈. 엔진은 `engine/` 에 있고(MIT 코드를 하네스용으로 다시 조립, 출처는 그 안의 THIRD_PARTY_NOTICES), 하네스가 쓰는 함수는 여기서 노출한다.

정본은 `docs/architecture/<이름>.<타입>.json` 이고 노드마다 `sources` 로 실제 파일·행 범위를
가리킨다. 엔진은 그 증거를 커밋 기준으로 검증하고 뷰어에 SRC 마커로 표시한다. 증거를 검증하지 않은
그림은 산문과 다를 바 없다. 이 모듈은 엔진을 호출하고 결과 기록(영수증)을 하네스 형식으로 감쌀 뿐
통과 여부는 판정하지 않는다. 판정은 `kernel/gates/arch_diagram.py` 가 한다.

  validate(kind, source)          스키마·배치·증거 진단 — 수정 루프에서 반복
  deliver(kind, source, output)   최종 렌더 + `<정본>.receipt.json`
  compare(base, head, output)     architecture 두 정본의 before·delta·after
  doctor()                        node·엔진 파일 상태

node 가 없으면 예외 대신 `{"ok": False, "tool_missing": "node"}` 를 돌려주고, 게이트는 이를 [TOOL] 로
표시한다. 검증을 엔진에 맡기는 조건은 엔진을 못 돌린 경우를 통과로 처리하지 않는 것이다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from kernel.context import ROOT

ENGINE = Path(__file__).resolve().parent / "engine"
CLI = ENGINE / "bin" / "engine.mjs"
DIAGRAM_DIR = "docs/architecture"
TYPES = ("architecture", "workflow", "sequence", "dataflow", "lifecycle")
NODE_KEY = {"architecture": "components", "workflow": "nodes", "sequence": "participants",
            "dataflow": "nodes", "lifecycle": "states"}
RECEIPT_SUFFIX = ".receipt.json"
ENGINE_TIMEOUT_SEC = 120
_REVISION = re.compile(r'("revision"\s*:\s*")[0-9a-fA-F]{40}(")')


def node_path() -> str | None:
    """`HARNESS_DIAGRAM_ENGINE=off` 면 node 가 없는 것으로 본다. 골든 출력 대조가 머신에 node 가 있든 없든
    같은 출력을 내게 하는 스위치다. 실제 엔진을 돌리는 테스트는 tests/test_harness_self.py 에 따로 있다."""
    if os.environ.get("HARNESS_DIAGRAM_ENGINE") == "off":
        return None
    return shutil.which("node")


def kind_of(source: Path) -> str | None:
    """`이름.<타입>.json` 에서 타입. 영수증·다른 파일이면 None."""
    name = source.name
    if name.endswith(RECEIPT_SUFFIX) or not name.endswith(".json"):
        return None
    parts = name[:-len(".json")].rsplit(".", 1)
    return parts[1] if len(parts) == 2 and parts[1] in TYPES else None


def receipt_path(source: Path) -> Path:
    return source.with_name(source.name[:-len(".json")] + RECEIPT_SUFFIX)


def output_path(source: Path) -> Path:
    return source.with_suffix(".html")


def spec_sha256_lf(source: Path) -> str:
    """CRLF 체크아웃과 LF 체크아웃에서 같은 값을 낸다. 영수증과 정본을 대조하는 키다."""
    return hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _run(args: list[str]) -> dict[str, object]:
    node = node_path()
    if not node:
        return {"ok": False, "tool_missing": "node"}
    if not CLI.exists():
        return {"ok": False, "tool_missing": str(CLI)}
    try:
        done = subprocess.run([node, str(CLI), *args, "--json"], cwd=str(ROOT), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=ENGINE_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"엔진이 {ENGINE_TIMEOUT_SEC}초 안에 응답하지 않았다"}
    try:
        receipt = json.loads(done.stdout)
    except ValueError:
        return {"ok": False, "error": (done.stderr or done.stdout).strip()[:2000], "exit": done.returncode}
    if not isinstance(receipt, dict):
        return {"ok": False, "error": "엔진 영수증이 JSON 객체가 아니다"}
    receipt.setdefault("ok", done.returncode == 0)
    return receipt


def _head_revision() -> str:
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return done.stdout.strip() if done.returncode == 0 else ""


def pin_revision(source: Path) -> str:
    """`meta.repository.revision` 에 HEAD 를 적어 정본 파일에 다시 쓴다. 40자 해시를 사람이 손으로 옮겨 적지 않게 한다.

    엔진은 이 커밋의 blob 으로 증거를 검증하므로 아직 커밋하지 않은 파일은 가리킬 수 없다.
    그래서 순서는 코드 커밋 → deliver → 그림 커밋이다. 반환값은 적은 revision 이고, 없으면 빈 문자열이다.
    """
    doc = load(source)
    repository = doc.get("meta", {}).get("repository") if isinstance(doc.get("meta"), dict) else None
    head = _head_revision()
    if not isinstance(repository, dict) or not head or repository.get("revision") == head:
        return head if isinstance(repository, dict) else ""
    # 값만 바꾼다. json.dumps 로 다시 쓰면 사람이 맞춰 둔 줄 배치가 전부 풀린다.
    text = source.read_text(encoding="utf-8")
    rewritten, count = _REVISION.subn(lambda m: f"{m.group(1)}{head}{m.group(2)}", text, count=1)
    if count != 1:
        repository["revision"] = head
        rewritten = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    source.write_text(rewritten, encoding="utf-8")
    return head


def validate(kind: str, source: Path) -> dict[str, object]:
    """판정만 하고 정본 파일은 다시 쓰지 않는다. 게이트가 Stop 훅에서 이 함수를 부르므로, 여기서 revision 을
    적으면 세션이 끝날 때마다 커밋된 정본에 변경이 생긴다. 실제로 났던 사고다(`dev/LESSONS.md` §23)."""
    return _run(["validate", kind, str(source), "--repo-root", str(ROOT)])


def _portable(engine: dict[str, object]) -> dict[str, object]:
    """엔진이 돌려준 입력·출력 경로를 레포 기준 상대 경로로 바꾼다. 영수증은 커밋되므로 로컬 체크아웃 위치가 드러나면 안 된다."""
    fixed = dict(engine)
    for key in ("input", "output"):
        value = fixed.get(key)
        if isinstance(value, str) and Path(value).is_absolute():
            try:
                fixed[key] = Path(value).resolve().relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                fixed[key] = Path(value).name
    return fixed


def deliver(kind: str, source: Path, output: Path | None = None) -> dict[str, object]:
    """렌더하고 하네스 영수증을 쓴다. 엔진이 실패하면 영수증을 쓰지 않으므로 이전 영수증이 그대로 남는다."""
    target = output or output_path(source)
    pin_revision(source)
    receipt = _run(["deliver", kind, str(source), str(target), "--repo-root", str(ROOT)])
    if not receipt.get("ok"):
        return receipt
    wrapped: dict[str, object] = {
        "ok": True,
        "schema": 1,
        "kind": kind,
        "source": source.relative_to(ROOT).as_posix() if source.is_absolute() else str(source),
        "output": target.relative_to(ROOT).as_posix() if target.is_absolute() else str(target),
        "spec_sha256_lf": spec_sha256_lf(source),
        "revision": _head_revision(),
        "delivered_at": datetime.now().isoformat(timespec="seconds"),
        "validation": receipt.get("validation"),
        "engine": _portable(receipt),
    }
    receipt_path(source).write_text(json.dumps(wrapped, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    # README 가 싣는 독립 SVG — HTML 과 같은 렌더에서 뽑으므로 둘이 어긋날 수 없다.
    from kernel.diagram import svg as _svg
    wrapped["svg_undefined_vars"] = sorted(_svg.export(target, target.with_suffix(".svg")))
    return wrapped


def compare(base: Path, head: Path, output: Path) -> dict[str, object]:
    return _run(["compare", "architecture", str(base), str(head), str(output),
                 "--repo-root", str(ROOT)])


def doctor() -> dict[str, object]:
    required = ("bin/engine.mjs", "assets/template.html", "renderers/shared/generated-validators.mjs",
                "delta/architecture-delta.mjs", "scripts/check-render-output.mjs")
    missing = [rel for rel in required if not (ENGINE / rel).exists()]
    node = node_path()
    version = ""
    if node:
        done = subprocess.run([node, "--version"], capture_output=True, text=True, encoding="utf-8")
        version = done.stdout.strip()
    return {"ok": bool(node) and not missing, "node": version or None, "engine": str(ENGINE),
            "missing": missing}


def load(source: Path) -> dict[str, object]:
    """정본 JSON 을 읽는다. 파싱할 수 없으면 빈 dict 를 돌려주고, '파싱 실패' 라고 알리는 것은 호출자 몫이다."""
    try:
        doc = json.loads(source.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


def diagnostics_lines(receipt: dict[str, object]) -> list[str]:
    """엔진 진단을 게이트 위반 문장으로. code · message · supportedFixes 만 남긴다."""
    found: list[str] = []
    for item in receipt.get("diagnostics") or []:
        if not isinstance(item, dict):
            continue
        fixes = " · ".join(str(fix) for fix in (item.get("supportedFixes") or []))
        message = str(item.get("message") or "").replace("\n", " ")[:300]
        found.append(f"{item.get('code')}: {message}" + (f" — 고치는 법: {fixes}" if fixes else ""))
    if not found and receipt.get("error"):
        found.append(str(receipt["error"])[:300])
    return found
