"""kernel/gates/md_graph.py — 문서와 실물의 대조 게이트.

MD 는 읽을거리가 아니라 다음 세션의 행동을 정하는 규칙이다. 그래서 코드와 같은 기준으로 검사한다.

  경로 참조 실존   MD 안 백틱 경로가 레포에 있는가. 삭제·리네임 후 남은 stale 참조를 잡는다
  문서↔코드 대조   같은 값이 문서와 코드 양쪽에 적힌 곳. 한쪽만 고치면 잡힌다
  고아 MD          허브에서 링크를 타고 도달 가능한가. 도달할 수 없으면 읽힐 때가 없는 문서다
  하네스 지도      훅·에이전트·스킬 실물이 지도에 등재됐는가

허브 목록도 대조 쌍도 프로파일이 정한다. 선언이 없으면 러너가 [SKIP] 으로 찍는다.
"""

from __future__ import annotations

import ast
import functools
import json
import re
from pathlib import Path

from kernel import profile
from kernel.context import READ_ENC, ROOT, _ls_files, _rel, read_list

MD_REF_ALLOWLIST_FILE = "md_ref_allowlist.txt"

_BACKTICK = re.compile(r"`([^`\n]+)`")
_PATH_TOKEN = re.compile(r"[\w][\w./-]*\.(?:py|tsx|ts|css|md|mjs|json)\b")
_MD_LINK = re.compile(r"\]\(([^)\s]+\.md)[^)]*\)")
_DOMAIN_MD = re.compile(r"^([a-z][a-z0-9_]*)/([A-Z][A-Z0-9_]*)\.md$")
_HOOK_CMD = re.compile(r"[\w./-]+\.(?:py|mjs|md)")


def _doc_md_files() -> list[Path]:
    """정본 MD — 작업 산출물·벤더 사본·동적 파일은 뺀다."""
    exclude = tuple(profile.MD["doc_exclude"])
    files: list[Path] = []
    for rel in _ls_files("*.md"):
        if not (ROOT / rel).exists() or "node_modules" in rel:
            continue
        if exclude and (rel.startswith(exclude) or rel in exclude):
            continue
        files.append(ROOT / rel)
    return files


def _load_ref_allowlist() -> set[str]:
    return read_list(ROOT / MD_REF_ALLOWLIST_FILE)


@functools.cache
def _tracked_set() -> set[str]:
    return set(_ls_files())


def _ref_exists(token: str, md_dir: Path) -> bool:
    """MD 는 파일명만 쓰기도 하고 패키지 상대 경로를 쓰기도 해서, 기준 디렉토리별 경로 해석과
    경로 끝부분 일치를 함께 쓴다. 어디에도 없는 파일명(이름을 바꾸거나 지운 뒤 남은 참조)만 없는
    것으로 본다 — 이 게이트가 실제로 잡으려는 것이 이것이다."""
    candidates = (token, "." + token)   # 백틱 파싱에서 맨 앞의 점(.)이 떨어져 나간다
    bases = [ROOT, md_dir]
    ui = profile.layer("ui")
    if ui:
        bases.append(ROOT / ui)
    for base in bases:
        for cand in candidates:
            if (base / cand).exists():
                return True
    for tracked in _tracked_set():
        for cand in candidates:
            if tracked == cand or tracked.endswith("/" + cand):
                return True
    return False


def check_md_path_refs() -> list[str]:
    allow = _load_ref_allowlist()
    skip_prefix = tuple(profile.MD["ref_exclude"])
    bad: list[str] = []
    for md in _doc_md_files():
        rel_md = _rel(md)
        for i, line in enumerate(md.read_text(encoding=READ_ENC).splitlines(), 1):
            for backtick in _BACKTICK.findall(line):
                for m in _PATH_TOKEN.finditer(backtick):
                    token = m.group(0)
                    if "*" in token or "/." in token or "//" in token or token in allow:
                        continue
                    if skip_prefix and token.startswith(skip_prefix):
                        continue
                    if not _ref_exists(token, md.parent):
                        bad.append(f"{rel_md}:{i}: 실존하지 않는 경로 참조 `{token}`")
    return bad


# ── 문서 ↔ 코드 대조 ───────────────────────────────────────────────────────────


def _top_level_ints(code: Path) -> dict[str, int]:
    consts: dict[str, int] = {}
    tree = ast.parse(code.read_text(encoding=READ_ENC))
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, int):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    consts[target.id] = node.value.value
    return consts


def _getenv_keys(code: Path) -> set[str]:
    keys: set[str] = set()
    tree = ast.parse(code.read_text(encoding=READ_ENC))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "getenv" and node.args \
                and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            keys.add(node.args[0].value)
    return keys


_CONST_REF = re.compile(r"\(([A-Z][A-Z0-9_]*)\b")
_NUMBER = re.compile(r"\d+")
_UPPER_TOKEN = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")


def _sync_int_consts(doc: Path, code: Path, marker: str) -> list[str]:
    """문서 표가 참조한 상수의 값이 그 줄의 숫자와 맞는지."""
    consts = _top_level_ints(code)
    rel_doc = _rel(doc)
    bad: list[str] = []
    for i, line in enumerate(doc.read_text(encoding=READ_ENC).splitlines(), 1):
        names = [n for n in _CONST_REF.findall(line) if marker in n]
        if not names:
            continue
        numbers = {int(n) for n in _NUMBER.findall(line)}
        for name in names:
            if name not in consts:
                bad.append(f"{rel_doc}:{i}: 문서가 참조한 {name} 가 {_rel(code)} 에 없음")
            elif numbers and consts[name] not in numbers:
                bad.append(f"{rel_doc}:{i}: {name}={consts[name]} 인데 문서 값 {sorted(numbers)} 불일치")
    return bad


def _sync_env_keys(doc: Path, code: Path, section: str, allow: tuple[str, ...]) -> list[str]:
    """코드가 읽는 환경변수 키와 문서 목록의 양방향 diff."""
    code_keys = _getenv_keys(code)
    doc_keys: set[str] = set()
    in_block = False
    for line in doc.read_text(encoding=READ_ENC).splitlines():
        if line.strip() == section:
            in_block = True
            continue
        if in_block:
            if line.strip().startswith("## "):
                break
            doc_keys.update(_UPPER_TOKEN.findall(line.split("#", 1)[0]))
    bad = [f"{_rel(code)} 가 읽는 '{k}' 가 {_rel(doc)} 목록에 없음"
           for k in sorted(code_keys - doc_keys)]
    bad += [f"{_rel(doc)} 의 '{k}' 를 {_rel(code)} 가 읽지 않음(타 모듈 로드 가능 — 확인)"
            for k in sorted(doc_keys - code_keys - set(allow))]
    return bad


def doc_sync_ready(entry: dict[str, object]) -> bool:
    """양쪽 실물이 다 있는가. 한쪽이라도 없으면 대조할 것이 없어 [SKIP] 이다.

    예전엔 여기서 조용히 빈 목록을 돌려줘 [OK] 로 찍혔다. 문서와 코드가 둘 다 없는 상태를
    "대조했고 어긋나지 않았다"로 보고하면 그건 게이트가 아니라 거짓말이다.
    """
    return (ROOT / str(entry["doc"])).exists() and (ROOT / str(entry["code"])).exists()


def check_doc_sync(entry: dict[str, object]) -> list[str]:
    """프로파일 DOC_SYNC 한 쌍을 판정한다."""
    doc = ROOT / str(entry["doc"])
    code = ROOT / str(entry["code"])
    if not doc_sync_ready(entry):
        return []
    kind = entry.get("kind")
    if kind == "int_consts":
        return _sync_int_consts(doc, code, str(entry.get("marker", "")))
    if kind == "env_keys":
        return _sync_env_keys(doc, code, str(entry.get("section", "")),
                              tuple(entry.get("allow", ())))   # type: ignore[arg-type]
    return [f"{_rel(doc)}: 알 수 없는 대조 종류 '{kind}' — 프로파일 DOC_SYNC 확인"]


# ── 고아 MD ────────────────────────────────────────────────────────────────────


def _is_domain_md(rel: str) -> bool:
    """`macro/MACRO.md` 처럼 패키지명과 파일명이 같은 정본. 라우팅표의 총칭 행(파일명 대신 '해당 패키지 MD' 로
    가리키는 행)으로 도달한 것으로 인정한다."""
    m = _DOMAIN_MD.match(rel)
    return bool(m) and m.group(1).upper().replace("-", "_") == m.group(2)


def _outlinks(md_path: Path, known: set[str]) -> set[str]:
    text = md_path.read_text(encoding=READ_ENC)
    tokens: set[str] = set()
    for backtick in _BACKTICK.findall(text):
        tokens.update(t for t in _PATH_TOKEN.findall(backtick) if t.endswith(".md"))
    tokens.update(_MD_LINK.findall(text))
    found: set[str] = set()
    for token in tokens:
        name = token.lstrip("./")
        for candidate in known:
            if candidate == name or candidate.endswith("/" + name):
                found.add(candidate)
    return found


def check_md_orphans() -> list[str]:
    """허브에서 참조 그래프로 도달 불가한 정본 MD — 읽힐 타이밍이 없는 문서."""
    if not profile.HUBS:
        return []
    files = _doc_md_files()
    known = {_rel(f) for f in files}
    by_rel = {_rel(f): f for f in files}
    reachable = {s for s in profile.HUBS if s in known}
    if profile.HUB_DOMAIN_MD_IMPLICIT:
        reachable |= {r for r in known if _is_domain_md(r)}
    frontier = list(reachable)
    while frontier:
        current = frontier.pop()
        for target in _outlinks(by_rel[current], known):
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    return [f"{rel}: 고아 — 허브에서 도달 불가. 라우팅표에 등재하거나 폐기하라"
            for rel in sorted(known - reachable)]


# ── 하네스 지도 ────────────────────────────────────────────────────────────────


def _harness_actuals() -> dict[str, set[str]]:
    actual: dict[str, set[str]] = {"훅": set(), "에이전트": set(), "스킬": set()}
    settings = ROOT / ".claude" / "settings.json"
    if settings.exists():
        raw = json.loads(settings.read_text(encoding=READ_ENC))
        for entries in (raw.get("hooks") or {}).values():
            for entry in entries:
                for hook in entry.get("hooks") or []:
                    for token in _HOOK_CMD.findall(hook.get("command") or ""):
                        # 실물이 `.claude/` 아래 있는 토큰만 훅으로 본다. 훅 명령문에는
                        # 안내 문구가 섞여 있어(`harness_install.py 를 돌려라`) 파일명처럼
                        # 생긴 문자열이 다 잡히면 지도에 없는 유령 훅이 계속 생긴다.
                        if (ROOT / token).is_file() and token.startswith(".claude/"):
                            actual["훅"].add(Path(token).name)
    agents = ROOT / ".claude" / "agents"
    if agents.is_dir():
        actual["에이전트"] = {p.stem for p in agents.glob("*.md")}
    skills = ROOT / ".claude" / "skills"
    if skills.is_dir():
        actual["스킬"] = {p.parent.name for p in skills.glob("*/SKILL.md")}
    return actual


_HOOK_FILE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.py")
_ITEM_NAME = re.compile(r"[a-z][a-z0-9-]*")


def _map_claims(text: str) -> dict[str, set[str]]:
    """지도가 "있다"고 적은 이름. **절 경계로 범위를 좁힌다** — 문서 전체에서 이름만 긁으면
    안내 문구에 섞인 파일명이 전부 유령 항목(실물 없이 지도에만 있는 이름)으로 잡힌다. 정방향
    검사도 같은 함정을 겪었다.

    훅은 표의 칸 위치가 일정하지 않아 절 안의 백틱 `*.py` 를 전부 본다. 에이전트·스킬은
    표 첫 칸이 이름이라 그 한 토큰만 본다 — 뒤 칸의 설명에 섞인 다른 이름을 배제한다.
    """
    claims: dict[str, set[str]] = {"훅": set(), "에이전트": set(), "스킬": set()}
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = next((kind for kind in claims if kind in line), "")
            continue
        if not section or not line.startswith("|"):
            continue
        tokens = _BACKTICK.findall(line)
        if section == "훅":
            claims[section].update(t for t in tokens if _HOOK_FILE.fullmatch(t))
        elif tokens and _ITEM_NAME.fullmatch(tokens[0]):
            claims[section].add(tokens[0])
    return claims


def check_harness_map() -> list[str]:
    """실물(훅·에이전트·스킬)과 지도가 빠짐없이 서로 대응하는지 양방향으로 본다.

    정방향은 실물이 지도에서 빠진 경우이고, 역방향은 실물은 지워졌는데 지도에만 남은 유령 항목이다.
    역방향은 **레포 어디에도 그 이름의 파일이 없을 때만** 유령으로 본다. 절 안에는 훅이
    아닌 파일명도 안내로 섞이는데(`harness_profile.py`), 실존 여부로 거르면 그 부류가
    통째로 빠진다. 대신 파일은 남았는데 settings.json 연결만 풀린 훅은 못 잡는다 — 그건 사람이 확인한다.

    이름의 존재만 보고 서술 내용은 검사하지 않는다. 그쪽은 주기 감사(`/md-audit`)다.
    """
    actuals = _harness_actuals()
    if not any(actuals.values()):
        return []
    doc = ROOT / profile.HARNESS_MAP
    if not doc.exists():
        return [f"{profile.HARNESS_MAP} 없음 — 하네스 지도가 정본이다"]
    text = doc.read_text(encoding=READ_ENC)
    bad = [f"{profile.HARNESS_MAP}: {kind} '{name}' 이 지도에 없음 — 같은 턴에 등재하라"
           for kind, names in actuals.items() for name in sorted(names) if name not in text]
    live = {Path(rel).name for rel in _tracked_set()}
    return bad + [f"{profile.HARNESS_MAP}: {msg}" for msg in _map_ghosts(text, actuals, live)]


def _map_ghosts(text: str, actuals: dict[str, set[str]], live: set[str]) -> list[str]:
    """지도에만 남은 이름. `live` 는 레포에 실존하는 파일 basename 집합이다."""
    return [f"{kind} '{name}' 은 지도에만 있음 — 실물이 없다. 행을 지워라"
            for kind, names in _map_claims(text).items()
            for name in sorted(names - actuals[kind]) if name not in live]


# 백틱 안 **빈 괄호** `이름()` 또는 `모듈.이름()` 만 잡는다. 인자 있는 `foo(x)` 까지 넓히면
# SQL 집계(`MAX(`)·CSS 함수(`var(`)가 같은 모양이라 오탐이 열 배가 된다 — 커버리지를
# 포기하고 신뢰도를 택했다(실제 운영해 보고 내린 판단). 인자 있는 표기의 실존은 사람이 하는
# 감사(/md-audit)가 맡는다.
_FN_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\(\s*\)")
# 정의부 — 파이썬·TS·Go 를 한 패턴으로 본다. 언어팩을 타지 않는 이유는 대상이 MD 이고,
# 그 MD 가 어느 언어를 가리키는지 백틱만 보고는 알 수 없기 때문이다.
_DEF_KEYWORDS = ("def", "class", "function", "const", "let", "var",
                 "interface", "type", "enum", "func")

# 언어·플랫폼 내장 함수. 어느 프로젝트에서도 레포가 실존을 책임지지 않으므로 커널이 기본으로
# 뺀다. 프로젝트 예외 파일(`md_ref_allowlist.txt`)에 매번 다시 적게 하면 그 파일이 내장 목록의
# 사본이 되고, 사본은 결국 원본과 어긋난다. CSS 는 특히 화면 정본 MD 에 그대로 등장한다.
_BUILTIN_CALLS = frozenset({
    # CSS
    "var", "calc", "clamp", "minmax", "repeat", "media", "url", "rgb", "rgba", "hsl", "hsla",
    "translate", "translateX", "translateY", "scale", "rotate", "blur", "linear-gradient",
    "cubic-bezier", "attr", "counter", "fit-content", "supports", "container",
    # 여러 언어 공통
    "print", "len", "range", "map", "filter", "sum", "min", "max", "int", "str", "float",
    "list", "dict", "set", "tuple", "bool", "type", "open", "format", "fetch", "require",
})


def _module_roots() -> set[str]:
    """레포 최상위 패키지·디렉토리 이름. `json.dumps()` 같은 외부 참조를 가려낸다."""
    roots: set[str] = set()
    for rel in _tracked_set():
        head = rel.split("/", 1)[0]
        roots.add(head.rsplit(".", 1)[0] if "." in head else head)
    return roots


def _fn_ref_sites() -> list[tuple[str, str]]:
    """(검사할 이름, 'MD경로:줄'). 템플릿 표기·외부 라이브러리·등재 예외를 걸러낸 뒤의 후보다."""
    allow = _load_ref_allowlist()
    roots = _module_roots()
    sites: list[tuple[str, str]] = []
    for md in _doc_md_files():
        rel_md = _rel(md)
        for number, line in enumerate(
                md.read_text(encoding=READ_ENC, errors="replace").splitlines(), 1):
            for chunk in _BACKTICK.findall(line):
                if "*" in chunk:
                    continue                # `init_*_db()` 류 템플릿 표기 — 이름이 아니다
                for token in _FN_CALL.findall(chunk):
                    if token in allow or token in _BUILTIN_CALLS:
                        continue
                    if "." in token:
                        if token.split(".")[0] not in roots:
                            continue        # stdlib·외부 라이브러리 — 실존은 우리 책임이 아니다
                        leaf = token.split(".")[-1]
                    else:
                        leaf = token
                    if leaf not in allow and leaf not in _BUILTIN_CALLS:
                        sites.append((leaf, f"{rel_md}:{number}"))
    return sites


def _defined_names(candidates: list[str]) -> set[str]:
    """후보 이름만 한 번에 훑는다 — 비용이 레포 크기가 아니라 후보 수에 비례한다."""
    if not candidates:
        return set()
    wanted = set(candidates)
    found: set[str] = set()
    pattern = re.compile(
        r"\b(?:" + "|".join(_DEF_KEYWORDS) + r")\s+([A-Za-z_][A-Za-z0-9_]*)")
    for rel in _tracked_set():
        if not rel.endswith((".py", ".ts", ".tsx", ".go", ".mjs", ".js")):
            continue
        path = ROOT / rel
        if not path.exists():
            continue
        for name in pattern.findall(path.read_text(encoding=READ_ENC, errors="replace")):
            if name in wanted:
                found.add(name)
        if found >= wanted:
            break
    return found


def check_md_fn_refs() -> list[str]:
    """MD 백틱의 `함수()` 가 코드에 실존하는지 — 개명 누락이 MD 를 거짓말로 만드는 것을 막는다.

    다음 세션은 MD 를 사실로 믿고 없는 함수를 부르려 한다. 경로 참조 게이트가 같은 일을
    파일 단위로 하는데, 개명은 파일보다 함수에서 훨씬 자주 일어난다.
    """
    sites = _fn_ref_sites()
    if not sites:
        return []
    defined = _defined_names(sorted({name for name, _ in sites}))
    return [f"{where}: 실존하지 않는 함수 참조 `{name}()` — 개명했으면 MD 도 같은 턴에 고친다"
            for name, where in sites if name not in defined]
