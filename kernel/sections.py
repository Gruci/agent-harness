"""kernel/sections.py — 러너의 등급 판정 헬퍼와 건너뜀 사유.

러너(`kernel/runner.py`)는 게이트를 나열하고 출력한다. 게이트 하나를 `[OK]`·`[SKIP]`·`[N/A]`·`[TOOL]` 중
무엇으로 찍을지 가르는 판정은 전부 여기 있다. 등급을 넷으로 가른 이유는 "설정을 안 채워서 못 함"·"이 언어엔
규칙이 성립 안 함"·"도구가 없어서 못 함"이 사용자가 해야 할 일이 전부 달라서다. 하나로 뭉뚱그리면 무엇을 잃었는지 모른다.

  SKIP  설정·대상이 없다        → 프로파일을 채우면 켜진다
  N/A   이 언어엔 해당 없다      → 손실이 아니다. 언어가 이미 보장하거나 개념이 없다
  TOOL  외부 도구가 없다         → 설치하면 켜진다

`CONDITIONAL` 은 대상이 생기기 전에는 판정할 것이 없는 게이트의 `[SKIP]` 사유다. 사유가 무엇이 생기면 무엇을
채우는지 말하므로 초기 설정이 `[SKIP]` 을 하나씩 판정하지 않는다(`.claude/skills/harness-init/SKILL.md` 6단계).
"""

from __future__ import annotations

from kernel import facts, linters, profile

# (slug, 제목, 위반 목록, 건너뜀). 건너뜀은 (등급, 사유) 이고 None 이면 실제로 검사한 것이다.
Skip = tuple[str, str]
Section = tuple[str, str, list[str], "Skip | None"]

NO_PY = "no source files to check"
NO_UI = "no UI source files"
# 웹·화면 게이트는 프레임워크팩의 선언을 읽는다. 팩을 안 고르면 조용히 통과하지 않고 이 사유로 [SKIP] 이다.
NO_SERVER_PACK = "no server framework pack selected — set FRAMEWORK in the profile"
NO_UI_PACK = "no UI framework pack selected — set FRAMEWORK in the profile"

# 조건부 게이트. 대상이 생기기 전에는 판정할 것이 없다. 사유가 무엇이 생기면 무엇을 채우는지 말하므로
# 초기 설정이 하나씩 판정하지 않는다. 대상이 이미 있는데 비어 있으면 그때 채운다.
CONDITIONAL_MARK = "conditional"
CONDITIONAL: dict[str, str] = {
    slug: f"{CONDITIONAL_MARK} — runs once the project has {subject}; then set {setting}"
    for slug, subject, setting in (
        ("abbrev_names", "banned abbreviations", "VOCAB['abbrev_names']"),
        ("abbrev_prefixes", "banned abbreviation prefixes", "VOCAB['abbrev_prefixes']"),
        ("ui_jargon", "banned UI words", "VOCAB['ui_denylist']"),
        ("ssl_bypass", "a global SSL verification patch", "SYMBOLS['ssl_bypass'] and FILES['ssl_util']"),
        ("routes_error", "a shared response wrapper every route returns", "SYMBOLS['error_response']"),
        ("browser_api", "a browser API wrapper", "ALLOWLIST['ui_platform']"),
        ("prompt_version", "versioned LLM prompt files", "VERSIONED_PROMPTS"),
        ("test_pairing", "collect or compute modules", "BEHAVIOR_TESTED_ROOTS"),
        ("ddl_types", "SQL DDL in source files", "CHECK_PATHS['schema']"),
    )
}


def entry(slug: str, title: str, violations: list[str], ok: object, need: str) -> Section:
    """ok 가 거짓이면 [SKIP]. `위반 0건`과 `대상 0개`를 구분하는 것이 이 함수의 전부다.

    언어팩이 이 게이트를 '해당 없음'으로 선언했으면 그쪽이 우선이다 — 설정을 채우라고
    안내해봐야 그 언어에서는 채울 것이 없다.
    """
    unneeded = profile.not_applicable(slug)
    if unneeded:
        return (slug, title, [], ("N/A", unneeded))   # 출처 이름은 profile 에서 병합할 때 이미 붙어 있다
    return (slug, title, violations, None) if ok else (slug, title, [], ("SKIP", need))


def syntax_section(slug: str, title: str, check: object, args: tuple,
                   ok: object, need: str, kind: str) -> Section:
    """구문 분석 결과(구문 사실)에 기대는 검사. `kind` 는 그 게이트가 읽는 사실의 종류다(`kernel/facts.py` 헤더 참고).

    선택한 언어의 분석기가 그 종류를 내지 못하면 **실행하지 않는다.** 파서 없이 돌리면 모든 파일이
    '파싱 실패' 위반이 되기 때문이다. 관용구 정규식 계열 검사는 언어팩의 `PATTERNS` 로
    바꿔 끼우므로 여기 오지 않는다. 여기 남은 것은 실제 파서가 필요한 검사뿐이다.
    확인 순서는 화면 린트(`ui_entry`)와 같이 N/A, SKIP(볼 소스 없음), TOOL(분석기 없음), 판정이다.
    """
    unneeded = profile.not_applicable(slug)
    if unneeded:
        return (slug, title, [], ("N/A", unneeded))   # 출처 이름은 profile 에서 병합할 때 이미 붙어 있다
    if not ok:
        return (slug, title, [], ("SKIP", need))     # 볼 소스가 없으면 분석기도 필요 없다
    reason = facts.unavailable(kind)
    if reason:
        return (slug, title, [], ("TOOL", reason))
    return entry(slug, title, check(*args), ok, need)   # type: ignore[operator]


def framework_section(slug: str, title: str, check: object, args: tuple,
                      ok: object, need: str, declares: str) -> Section:
    """서버 프레임워크팩이 판정 방식을 선언했을 때만 도는 검사(13·16). 확인 순서는 N/A, SKIP(팩 미선택),
    N/A(팩이 그 판정을 선언하지 않음 — 이 프레임워크에서 성립하지 않는다), 그다음이 구문 사실 검사다."""
    unneeded = profile.not_applicable(slug)
    if unneeded:
        return (slug, title, [], ("N/A", unneeded))
    server = profile.SERVER
    if server is None:
        return (slug, title, [], ("SKIP", NO_SERVER_PACK))
    if not server[declares]:
        return (slug, title, [], ("N/A", f"{server['NAME']}: does not apply to this framework"))
    return syntax_section(slug, title, check, args, ok, need, "python")


def pack_section(slug: str, title: str, check: object, args: tuple, ok: object, need: str,
                 declared: object, kind: str | None = None) -> Section:
    """팩 선언(NAMING·OWNED 등)에 기대는 검사. 확인 순서는 N/A, SKIP(볼 소스 없음), N/A(팩이 선언하지 않음),
    TOOL(구문 사실이 필요한데 분석기 없음), 판정이다. 선언이 없는 언어에서 대상 0건 [OK] 를 내지 않는 것이 요점이다."""
    unneeded = profile.not_applicable(slug)
    if unneeded:
        return (slug, title, [], ("N/A", unneeded))
    if not ok:
        return (slug, title, [], ("SKIP", need))
    if not declared:
        return (slug, title, [], ("N/A", "the selected language and framework packs declare nothing for this check"))
    reason = facts.unavailable(kind) if kind else ""
    if reason:
        return (slug, title, [], ("TOOL", reason))
    return (slug, title, check(*args), None)   # type: ignore[operator]


def ui_entry(slug: str, title: str, lint: linters.UiLint, ok: object, need: str,
             extra: list[str] | None = None) -> Section:
    """ESLint 에 맡긴 화면 린터 결과에서 slug 하나의 섹션을 만든다. 확인 순서는 N/A, SKIP(대상·설정 없음), TOOL(eslint 없음), 판정이다.
    `extra` 는 같은 규칙을 스크립트 밖(스타일시트·템플릿)에서 찾은 결과다(kernel/gates/ui_styles.py)."""
    unneeded = profile.not_applicable(slug)
    if unneeded:
        return (slug, title, [], ("N/A", unneeded))
    if not ok:
        return (slug, title, [], ("SKIP", need))
    if lint.missing:
        return (slug, title, [], ("TOOL", lint.missing))
    return (slug, title, lint.found.get(slug, []) + list(extra or ()), None)


def linter_sections() -> list[Section]:
    """언어팩이 선언한 표준 린터에 검사를 맡긴 결과."""
    found: list[Section] = []
    for slug, title, violations, skipped in linters.sections():
        found.append((slug, title, violations, ("TOOL", skipped) if skipped else None))
    return found


def need_layer(name: str) -> str:
    return f"no {name} folder set in the profile"


def need_symbol(name: str) -> str:
    return f"no {name} name set in the profile"
