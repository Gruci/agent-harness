"""kernel/profile.py — 프로젝트가 커널에 알려주는 것 전부.

커널은 이 모듈을 통해서만 프로젝트를 안다. 실물은 `<프로젝트 루트>/harness_profile.py` 이고,
없으면 전부 기본값(대체로 비어 있음)이라 레이어를 요구하는 게이트는 [SKIP] 이 된다.

**비어 있으면 조용히 통과하는 게 아니라 [SKIP] 으로 찍힌다.** 이 구분 때문에 이 파일이 있다.
이전 하네스는 레이어 이름이 안 맞아 검사 대상이 0개인데도 [OK] 로 통과시켰고, 그래서 실제로는
아무것도 검사하지 않는 게이트를 믿게 만들었다.

스키마 정의와 각 항목의 뜻은 `profiles/_template.py` 가 정본이다.
"""

from __future__ import annotations

import importlib.util
import re
from typing import Any

from kernel import PROFILE_SCHEMA as _REQUIRED_SCHEMA, UPSTREAM, arch, framework, lang
from kernel.context import KERNEL_HOME, PROFILE_FILE, ROOT, git_output

_CHECK_PATH_KEYS = ("ui", "ui_admin", "ui_tokens", "tests", "routes", "schema")
_FILE_KEYS = ("settings", "ssl_util")
_SYMBOL_KEYS = ("ssl_bypass", "error_response")
_VOCAB_KEYS = ("ui_denylist", "abbrev_prefixes", "abbrev_names")
_ALLOWLIST_KEYS = ("py_any", "ui_hex", "ui_fetch", "ui_fetch_wrappers", "env_access",
                   "ui_platform")
_MD_KEYS = ("doc_exclude", "ref_exclude", "style_exclude", "date_exempt")


def _load() -> Any:
    path = ROOT / PROFILE_FILE
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("harness_profile", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MOD = _load()

# ── 프로파일 형식 검사 ────────────────────────────────────────────────────────
#
# 파이썬 모듈이라 오타가 예외를 안 낸다. `LAYER = {...}` 는 그냥 무시되고 그 게이트가 [SKIP]
# 이 되며, `SCOPE["exclude_all"] = "tests/"` 처럼 튜플 자리에 문자열을 적으면 `tuple()` 이
# 글자 단위로 쪼개 `startswith(("t","e","s",...))` 가 돼 **소스 대부분이 조용히 검사에서
# 빠진다.** 둘 다 화면에는 아무 경고도 뜨지 않는다. 그래서 값을 변환(coerce)하기 전에 형식부터 검사한다.
_KNOWN_NAMES = frozenset({
    "STAGE", "LANG", "ARCH", "FRAMEWORK", "SYNTAX", "SOURCE_EXT", "UI_EXT", "PATTERNS", "NOT_APPLICABLE",
    "LINTERS", "CHECK_PATHS", "FILES", "SYMBOLS", "VOCAB", "ALLOWLIST", "MD", "SCOPE", "HUBS",
    "HUB_DOMAIN_MD_IMPLICIT", "DOC_SYNC", "BEHAVIOR_TESTED_ROOTS", "LOCAL_GATES", "LOCAL_HOOKS", "HARNESS_MAP",
    "ROOT_FILES", "LEGACY_PATHS", "LESSONS_DOC", "AGENT_MODEL_POLICY", "MAINTENANCE",
    "VERSIONED_PROMPTS", "UI_COPY", "HARNESS_SELF", "PRESET_SUMMARY",
    "PRESET_FITS", "PROFILE_SCHEMA", "UI_NPM_DIR", "COMPONENT_GRAPH", "MERGE_FLOW", "NAMING", "OWNED", "TEAM",
})
_STR_NAMES = ("STAGE", "LANG", "ARCH", "SYNTAX", "HARNESS_MAP", "LESSONS_DOC", "UI_NPM_DIR", "COMPONENT_GRAPH",
              "MERGE_FLOW")
MERGE_FLOWS = ("direct", "pr")
_DICT_NAMES = ("CHECK_PATHS", "FILES", "SYMBOLS", "VOCAB", "ALLOWLIST", "MD", "SCOPE", "PATTERNS",
               "NOT_APPLICABLE", "AGENT_MODEL_POLICY", "MAINTENANCE", "UI_COPY", "NAMING", "OWNED", "TEAM")
_SEQ_NAMES = ("HUBS", "DOC_SYNC", "BEHAVIOR_TESTED_ROOTS", "LOCAL_GATES", "LOCAL_HOOKS", "ROOT_FILES",
              "SOURCE_EXT", "UI_EXT", "LINTERS", "LEGACY_PATHS", "VERSIONED_PROMPTS", "FRAMEWORK")
_SUB_KEYS = {
    "CHECK_PATHS": _CHECK_PATH_KEYS, "FILES": _FILE_KEYS, "SYMBOLS": _SYMBOL_KEYS, "VOCAB": _VOCAB_KEYS,
    "ALLOWLIST": _ALLOWLIST_KEYS, "MD": _MD_KEYS, "SCOPE": ("exclude_all", "exclude_scratch"),
}
_SEQ_VALUED = ("VOCAB", "ALLOWLIST", "MD", "SCOPE")
_PATH_VALUED = ("CHECK_PATHS", "FILES", "SYMBOLS")


def _is_seq(value: object) -> bool:
    return isinstance(value, (list, tuple))


def _shape_errors(mod: Any) -> list[str]:
    """프로파일 원문의 형식 위반을 찾는다. 설정 이름 오타, 튜플 자리에 쓴 문자열, 모르는 하위 키가 대상이다."""
    if mod is None:
        return [f"{PROFILE_FILE}: set up a profile with PROFILE_SCHEMA = {_REQUIRED_SCHEMA} and a component graph first"]
    found: list[str] = []
    for name in vars(mod):
        if name.isupper() and len(name) > 1 and name not in _KNOWN_NAMES:
            found.append(f"{PROFILE_FILE}: unknown setting {name} — a typo means the setting is silently ignored")
    for name in _STR_NAMES:
        value = getattr(mod, name, None)
        if value is not None and not isinstance(value, str):
            found.append(f"{PROFILE_FILE}: {name} must be a string — current type is {type(value).__name__}")
    flow = getattr(mod, "MERGE_FLOW", "direct")
    if isinstance(flow, str) and flow not in MERGE_FLOWS:
        found.append(f"{PROFILE_FILE}: MERGE_FLOW must be one of {' '.join(MERGE_FLOWS)} — current value is {flow!r}")
    team = getattr(mod, "TEAM", {})
    if isinstance(team, dict) and team:
        required = {"url", "repository", "token_env"}
        if set(team) - (required | {"timeout"}) or any(not isinstance(team.get(k), str) or not team[k].strip() for k in required):
            found.append(f"{PROFILE_FILE}: TEAM requires url, repository and token_env strings; optional timeout only")
        if flow != "pr":
            found.append(f"{PROFILE_FILE}: TEAM requires MERGE_FLOW = 'pr'; shared integration owns main")
    schema = getattr(mod, "PROFILE_SCHEMA", None)
    if getattr(mod, "COMPONENT_GRAPH", "docs/architecture/components.json") != "docs/architecture/components.json":
        found.append(f"{PROFILE_FILE}: COMPONENT_GRAPH must be docs/architecture/components.json")
    if schema != _REQUIRED_SCHEMA or isinstance(schema, bool):
        found.append(f"{PROFILE_FILE}: cannot run with schema version {schema!r} — set PROFILE_SCHEMA = {_REQUIRED_SCHEMA}")
    for name in _DICT_NAMES:
        value = getattr(mod, name, None)
        if value is not None and not isinstance(value, dict):
            found.append(f"{PROFILE_FILE}: {name} must be a dict — current type is {type(value).__name__}")
    for name in _SEQ_NAMES:
        value = getattr(mod, name, None)
        if value is not None and not _is_seq(value):
            found.append(f"{PROFILE_FILE}: {name} must be a tuple — wrap a single value as ('x',)")
    for name, keys in _SUB_KEYS.items():
        mapping = getattr(mod, name, None)
        if not isinstance(mapping, dict):
            continue
        for key, value in mapping.items():
            if key not in keys:
                found.append(f"{PROFILE_FILE}: {name}[{key!r}] is an unknown key — allowed: {' '.join(keys)}")
            elif name in _SEQ_VALUED and value is not None and not _is_seq(value):
                found.append(f"{PROFILE_FILE}: {name}[{key!r}] must be a tuple — a bare string splits into characters")
            elif name in _PATH_VALUED and value is not None and not isinstance(value, str):
                found.append(f"{PROFILE_FILE}: {name}[{key!r}] must be a path string or None")
    for name, error in (("NAMING", lang.valid_naming(getattr(mod, "NAMING", {}))),
                        ("OWNED", lang.valid_patterns(getattr(mod, "OWNED", {}), None, allow_none=True))):
        if error and isinstance(getattr(mod, name, {}), dict):
            found.append(f"{PROFILE_FILE}: {name} {error}")
    return found


PROFILE_ERRORS: list[str] = _shape_errors(_MOD)


def _dict(name: str) -> dict[str, Any]:
    """형식이 틀린 선언은 없는 것으로 읽는다. 형식 위반은 PROFILE_ERRORS 가 따로 출력한다."""
    given = getattr(_MOD, name, None) if _MOD else None
    return given if isinstance(given, dict) else {}


def _seq(name: str, default: tuple = ()) -> tuple:
    """튜플 자리의 문자열을 글자 단위로 쪼개지 않는다."""
    given = getattr(_MOD, name, None) if _MOD else None
    return tuple(given) if _is_seq(given) else default


def _mapping(name: str, keys: tuple[str, ...], empty: object) -> dict[str, Any]:
    given = _dict(name)
    return {key: given.get(key) if empty is None else given.get(key, empty) for key in keys}


STAGE: str = getattr(_MOD, "STAGE", "greenfield") if _MOD else "greenfield"
LOADED: bool = _MOD is not None
# 프로파일이 선언한 서식 버전. 선언하지 않았으면 0 이다.
PROFILE_SCHEMA: int = (
    getattr(_MOD, "PROFILE_SCHEMA", 0) if _MOD and isinstance(getattr(_MOD, "PROFILE_SCHEMA", 0), int) else 0
)

# 하네스 레포 자신의 프로파일인가. clone 해 간 프로젝트에서 이게 참이면 아직 설정 전이다 —
# 설치 스크립트가 프리셋으로 덮어쓴다.
IS_HARNESS_SELF: bool = bool(getattr(_MOD, "HARNESS_SELF", False)) if _MOD else False

COMPONENT_GRAPH: str = getattr(_MOD, "COMPONENT_GRAPH", "docs/architecture/components.json")
# 끝난 과업을 본체에 합치는 방식 — kernel/task_finish.py 가 읽는다. 선언하지 않으면 ff 로 바로 합친다.
MERGE_FLOW: str = getattr(_MOD, "MERGE_FLOW", "direct") if _MOD else "direct"

CHECK_PATHS = _mapping("CHECK_PATHS", _CHECK_PATH_KEYS, None)
FILES = _mapping("FILES", _FILE_KEYS, None)
SYMBOLS = _mapping("SYMBOLS", _SYMBOL_KEYS, None)
VOCAB = _mapping("VOCAB", _VOCAB_KEYS, ())
ALLOWLIST = _mapping("ALLOWLIST", _ALLOWLIST_KEYS, ())
MD = _mapping("MD", _MD_KEYS, ())

SCOPE = {key: tuple(value) if _is_seq(value := _dict("SCOPE").get(key, ())) else ()
         for key in ("exclude_all", "exclude_scratch")}
HUBS: tuple[str, ...] = _seq("HUBS")
HUB_DOMAIN_MD_IMPLICIT: bool = getattr(_MOD, "HUB_DOMAIN_MD_IMPLICIT", True) if _MOD else True
DOC_SYNC: list[dict[str, Any]] = list(_seq("DOC_SYNC"))
BEHAVIOR_TESTED_ROOTS: tuple[str, ...] = _seq("BEHAVIOR_TESTED_ROOTS")
LOCAL_GATES: tuple[str, ...] = _seq("LOCAL_GATES")
# 프로젝트 PreToolUse 훅 — `harness_hooks/<이름>.py`. 실행과 자가 시험은 kernel/local_hooks.py 가 한다.
LOCAL_HOOKS: tuple[str, ...] = _seq("LOCAL_HOOKS")
HARNESS_MAP: str = getattr(_MOD, "HARNESS_MAP", "HARNESS.md") if _MOD else "HARNESS.md"
ROOT_FILES: tuple[str, ...] = _seq("ROOT_FILES")

# ── 언어 ───────────────────────────────────────────────────────────────────────
#
# 게이트가 볼 파일 확장자와, 구문 분석이나 언어 관용구에 기대는 검사를 돌릴 수 있는지를 정한다.
# 구문 분석 결과(구문 사실)를 못 받은 검사는 [OK] 가 아니라 [TOOL] 이 된다(판정은 `kernel/facts.py`).
# 파이썬용 정규식이 다른 언어에서 안 걸린 것을 "위반 없음"으로 보고하면 검사 없이 통과한 것과 같다.
LANG: str | None = getattr(_MOD, "LANG", None) if _MOD else None
try:
    _PACK = lang.load(LANG) if LANG is not None else lang.unselected()
except ValueError as exc:
    PROFILE_ERRORS.append(f"{PROFILE_FILE}: {exc}")
    _PACK = lang.unselected()

# 선택한 언어팩 전체. 분석기(`kernel/facts.py`)가 QUERIES·MODULE_RULE·PUBLIC_RULE 을 여기서 읽는다.
PACK: dict[str, Any] = _PACK

SOURCE_EXT: tuple[str, ...] = _seq("SOURCE_EXT", tuple(_PACK["EXT"]))
SYNTAX: str | None = getattr(_MOD, "SYNTAX", _PACK["SYNTAX"]) if _MOD else _PACK["SYNTAX"]

# ── 프레임워크 ────────────────────────────────────────────────────────────────
#
# 웹·화면 게이트가 어느 프레임워크의 선언을 읽을지 정한다. 역할은 server·ui 둘이고 역할별로 하나씩이다.
# 선언하지 않으면 그 역할의 게이트는 조용히 통과하는 게 아니라 [SKIP](프레임워크팩 미선택)으로 찍힌다.
FRAMEWORK: tuple[str, ...] = _seq("FRAMEWORK")
try:
    _FRAMEWORKS = framework.load(FRAMEWORK)
except ValueError as exc:
    PROFILE_ERRORS.append(f"{PROFILE_FILE}: {exc}")
    _FRAMEWORKS = framework.unselected()

# 역할별 팩. None 이면 미선택이다. 서버팩은 kernel/gates/orphan_api.py·layers.py 가, 화면팩은 kernel/linters.py 가 읽는다.
SERVER: dict[str, Any] | None = _FRAMEWORKS["server"]
UI: dict[str, Any] | None = _FRAMEWORKS["ui"]

# 화면 소스 패턴의 기본값은 화면팩이 준다. 프로파일이 명시하면 그것이 이긴다 — 언어팩의 SOURCE_EXT 와 같은 규칙이다.
# 빈 튜플은 선언이 아니다 — 템플릿이 `UI_EXT = ()` 를 실어 보내 React 팩 기본값을 덮고 화면 검사 6종을 깨뜨렸다.
UI_EXT: tuple[str, ...] = _seq("UI_EXT") or (tuple(UI["UI_EXT"]) if UI else ())

# 언어팩이 준 것 위에 프로파일이 덮어쓴다 — 프로젝트 사정이 언어 관례보다 우선이다.
PATTERNS: dict[str, str] = dict(_PACK["PATTERNS"])
if _MOD and getattr(_MOD, "PATTERNS", None):
    PATTERNS.update(_MOD.PATTERNS)

# ── 아키텍처 ──────────────────────────────────────────────────────────────────
#
# 이 프로젝트 형태에 어떤 레이어가 있는지 정한다. 선언하지 않으면(None) 어떤 검사도 N/A 로 돌리지 않는다.
ARCH: str | None = getattr(_MOD, "ARCH", None) if _MOD else None
try:
    _ARCH_PACK = arch.load(ARCH)
except ValueError as exc:
    PROFILE_ERRORS.append(f"{PROFILE_FILE}: {exc}")
    _ARCH_PACK = {"NOT_APPLICABLE": {}}


def _na_prefixed(entries: dict[str, str], tag: str | None) -> dict[str, str]:
    """N/A 사유 앞에 출처 이름을 미리 붙여 둔다. 러너는 이 문자열을 그대로 출력한다."""
    label = tag or "undeclared"
    return {slug: f"{label}: {reason}" for slug, reason in entries.items()}


# 병합 순서는 언어팩, 아키텍처팩, 프로파일이고 나중에 병합한 값이 앞의 값을 덮어쓴다.
# 프로젝트 사정이 언어·아키텍처 관례보다 우선한다는 기존 원칙을 그대로 따른 것이다.
NOT_APPLICABLE: dict[str, str] = _na_prefixed(dict(_PACK["NOT_APPLICABLE"]), SYNTAX)
NOT_APPLICABLE.update(_na_prefixed(_ARCH_PACK["NOT_APPLICABLE"], ARCH))
if _MOD and getattr(_MOD, "NOT_APPLICABLE", None):
    NOT_APPLICABLE.update(_na_prefixed(dict(_MOD.NOT_APPLICABLE), SYNTAX))

LINTERS: tuple = _seq("LINTERS", tuple(_PACK["LINTERS"]))

# 이름 표기(kernel/gates/naming.py) — 언어팩 위에 프로파일이 키별로 덮는다. None 은 그 판정을 끈다.
# 덮기 전 값(`*_OVERRIDE`)은 편집 표면(harness_gates/edit_surface.py)이 끄기·넓히기·바꿔치기를 세려고 따로 둔다.
NAMING_OVERRIDE: dict[str, str | None] = _dict("NAMING")
NAMING: dict[str, str] = {key: value for key, value in {**_PACK["NAMING"], **NAMING_OVERRIDE}.items() if value}
# 한 주인 기능(kernel/gates/owners.py). 프로파일 OWNED 가 같은 가족 이름을 덮고 None 이면 끈다. 화면팩에 없는 새 가족은 서버 쪽이다.
OWNED_OVERRIDE: dict[str, str | None] = _dict("OWNED")
_UI_FAMILIES = dict(UI["OWNED"]) if UI else {}
OWNED_FAMILIES: frozenset[str] = frozenset({**_PACK["OWNED"], **_UI_FAMILIES})
OWNED: dict[str, str] = {name: rule for name, rule in
                         {**_PACK["OWNED"], **{k: v for k, v in OWNED_OVERRIDE.items() if k not in _UI_FAMILIES}}.items()
                         if rule}
UI_OWNED: dict[str, str] = {name: rule for name, rule in
                            {**_UI_FAMILIES, **{k: v for k, v in OWNED_OVERRIDE.items() if k in _UI_FAMILIES}}.items()
                            if rule}


def pattern(name: str) -> str:
    """선택한 언어가 선언한 관용구. 선언이 없으면 빈 문자열이다."""
    return PATTERNS.get(name, "")


def not_applicable(slug: str) -> str:
    """이 언어·아키텍처에서 규칙 자체가 성립하지 않으면 그 사유. 아니면 빈 문자열."""
    return NOT_APPLICABLE.get(slug, "")
LEGACY_PATHS: tuple[tuple[str, "str | None"], ...] = _seq("LEGACY_PATHS")
LESSONS_DOC: str | None = getattr(_MOD, "LESSONS_DOC", None) if _MOD else None
AGENT_MODEL_POLICY: dict[str, tuple[str, str]] = (
    dict(getattr(_MOD, "AGENT_MODEL_POLICY", {})) if _MOD else {}
)
# 월간 감사 알림을 띄우는 임계치를 항목별로 덮어쓴다. 기본값은 kernel/maintenance.py 에 있다.
MAINTENANCE: dict[str, dict[str, int]] = (
    dict(getattr(_MOD, "MAINTENANCE", {})) if _MOD else {}
)
# 헤더의 `V<major>.<minor>` 버전을 올리도록 강제할 LLM 프롬프트 파일 목록. 비어 있으면 그 게이트는 [SKIP] 이다.
VERSIONED_PROMPTS: tuple[str, ...] = _seq("VERSIONED_PROMPTS")
# UI 문구를 LLM 으로 검수하는 훅에 넘길 도메인 정보. "context" 는 업종·제품을 설명하는 한 줄이고,
# "product_terms" 는 위반으로 보지 않을 도메인 필수 용어다. 판정 기준은 범용이라 커널이 갖고, 여기서는 맥락만 준다.
UI_COPY: dict[str, Any] = dict(getattr(_MOD, "UI_COPY", {})) if _MOD else {}
TEAM: dict[str, Any] = dict(getattr(_MOD, "TEAM", {})) if _MOD and isinstance(getattr(_MOD, "TEAM", {}), dict) else {}


def layer(name: str) -> str | None:
    """레이어 경로 접두. 선언이 없으면 None — 그 게이트는 [SKIP] 이다."""
    value = CHECK_PATHS.get(name)
    if not value:
        return None
    return value if value.endswith("/") else value + "/"


def layer_raw(name: str) -> str | None:
    """접두 슬래시를 붙이지 않은 원문. 파일 하나를 가리키는 레이어(스키마 모듈 등)에 쓴다."""
    return CHECK_PATHS.get(name) or None


def symbol(name: str) -> str | None:
    return SYMBOLS.get(name) or None


def scratch() -> tuple[str, ...]:
    return SCOPE["exclude_scratch"]


# 화면 린터(검사 10·17~20·42)를 돌릴 npm 프로젝트 폴더, 즉 node_modules 가 들어 있는 폴더. 없으면 ui 레이어 경로의 첫 세그먼트를 쓴다.
UI_NPM_DIR: str | None = getattr(_MOD, "UI_NPM_DIR", None) if _MOD else None


_TEMPLATE_NAME = re.compile(r"^([A-Z][A-Z_]+)\s*[:=]", re.M)


def outdated_notice() -> str:
    """프로파일이 커널 서식보다 오래됐으면 안내문을, 아니면 빈 문자열을 돌려준다.

    프로파일에 없는 새 키는 `getattr` 기본값을 받아 조용히 [SKIP] 이 된다. "설정을 안 적었다"와 "이 프로파일이
    커널보다 오래됐다"는 사람이 할 일이 다르므로 후자는 세션 시작 때 따로 알린다. 새 항목 목록은 서식
    정본(`profiles/_template.py`)의 대문자 이름 중 프로파일에 없는 것을 뽑아 만든다. 목록 표를 따로 두지 않는다.
    """
    from kernel import PROFILE_SCHEMA as required

    if _MOD is not None and PROFILE_SCHEMA == required:
        return ""
    template = KERNEL_HOME / "profiles" / "_template.py"
    names = set(_TEMPLATE_NAME.findall(template.read_text(encoding="utf-8"))) if template.exists() else set()
    missing = sorted(n for n in names - set(vars(_MOD) if _MOD else ()) if n not in ("PRESET_SUMMARY", "PRESET_FITS"))
    return (f"[PROFILE SCHEMA] {PROFILE_FILE} is schema {PROFILE_SCHEMA} but the kernel requires {required} — "
            f"new settings to fill: {' '.join(missing) or 'none'}. Fill them per profiles/_template.py, "
            f"then set PROFILE_SCHEMA = {required}.")


_GITHUB_REPO = re.compile(r"github\.com[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?/*$", re.I)


def repo_key(url: str) -> str:
    """GitHub 주소를 `소유자/레포` 로 줄여 https·ssh 표기 차이를 지운다. GitHub 가 아니면 원문 그대로다."""
    found = _GITHUB_REPO.search(url.strip())
    return found.group(1).lower() if found else url.strip().lower()


def remote_urls() -> list[str]:
    """이 체크아웃의 모든 원격 주소. git 밖이거나 원격이 없으면 빈 목록이다."""
    out = git_output("config", "--get-regexp", r"^remote\..*\.url$") or ""
    return [line.split(None, 1)[1] for line in out.splitlines() if len(line.split(None, 1)) == 2]


def setup_notice(remotes: list[str]) -> str:
    """설치가 덜 끝난 체크아웃이면 세션 시작에 줄 안내, 아니면 빈 문자열.

    첫 커밋 SHA 비교는 얕은 clone 에서 틀리고, 설치 표식 파일은 clone 과 원류가 바이트까지 같아 둘 자리가 없다.
    원격 주소는 원류 체크아웃(origin)과 fork(upstream)를 덮고, README 흐름의 clone(`rm -rf .git`)은 원격이 없다.
    """
    if IS_HARNESS_SELF and repo_key(UPSTREAM) not in {repo_key(url) for url in remotes}:
        return ("[HARNESS SETUP] This checkout still has the harness repo's own profile, so no gate knows this "
                "project yet. Before any code, run the harness-init skill: ask what the user is building, then run "
                f"`python -X utf8 harness_install.py`. Developing the harness itself? Add a remote for {UPSTREAM}.")
    if LOADED and not IS_HARNESS_SELF and LANG is None:
        return ("[HARNESS SETUP] No product language is set (LANG = None), so every gate that reads source is "
                "[SKIP]. Finish the stack step of the harness-init skill before the first code.")
    return ""


if __name__ == "__main__":
    for notice in (setup_notice(remote_urls()), outdated_notice()):
        if notice:
            print(notice)
