"""kernel/runner.py — 게이트를 모아 돌리고 결과를 등급으로 찍는다.

사용:
  python -X utf8 -m kernel.runner                전 게이트. 위반이 있으면 exit 1
  python -X utf8 -m kernel.runner --file <경로>  방금 저장한 파일 하나만 (작성 시점 훅 경유)

출력 등급:
  [OK]     검사했고 위반 0건
  [SKIP]   **검사할 대상이 없었다.** 프로파일에 레이어·어휘 선언이 없으면 여기로 온다
  [FAIL]   강제 위반 — 총계에 합산되고 exit 1 을 만든다
  [REPORT] 참고용 신호 — 오탐 여지가 있어 합산하지 않는다. 레포 전체에 걸친 신호(경로 참조·stale 노드)는
           전체 검사 모드에서만 찍는다. 작성 시점에 찍으면 편집한 파일과 무관한 소음이라 모델이 출력을 안 읽게 된다

[OK] 와 [SKIP] 을 가르는 것이 이 러너의 핵심이다. 이전 하네스는 레이어 이름이 안 맞아 대상이
0개인데도 [OK] 로 찍었고, 그래서 실제로는 아무것도 검사하지 않는 게이트를 믿게 만들었다.

각 섹션은 slug 를 갖는다. slug 는 `harness_baseline.txt` 의 동결 키로도 쓰인다. 설치 시점에
이미 있던 위반을 (slug, 파일) 단위로 기록해 예외 처리하고, 모든 게이트가 통과한 상태에서 출발하게 하려는 것이다.
"""

from __future__ import annotations

import fnmatch
import importlib
import sys
from pathlib import Path

from kernel import diagram, facts, graph_checks, linters, profile
# 러너를 거쳐 쓰도록 다시 내보낸다. trace 는 violation_path 를, 설치 스크립트는 BASELINE_FILE·load_baseline 을 쓴다.
from kernel.baseline import (BASELINE_FILE, apply_baseline as _apply_baseline,  # noqa: F401
                             load_baseline, violation_path)
from kernel.context import ROOT, _rel, app_code, is_harness_own, tracked
from kernel.gates import (api_types, arch_diagram, core, duplication, harness_self, layers,
                          md_graph, md_style, orphan_api, placement, prompt_version, schema,
                          tests_pairing)

# (slug, 제목, 위반 목록, 건너뜀). 건너뜀은 (등급, 사유) 이고 None 이면 실제로 검사한 것이다.
#
# 등급을 셋으로 가른 이유: "설정을 안 채워서 못 함"·"이 언어엔 규칙이 성립 안 함"·"도구가
# 없어서 못 함"은 사용자가 해야 할 일이 전부 다르다. 하나로 뭉뚱그리면 무엇을 잃었는지 모른다.
#   SKIP  설정·대상이 없다        → 프로파일을 채우면 켜진다
#   N/A   이 언어엔 해당 없다      → 손실이 아니다. 언어가 이미 보장하거나 개념이 없다
#   TOOL  외부 도구가 없다         → 설치하면 켜진다
Skip = tuple[str, str]
Section = tuple[str, str, list[str], "Skip | None"]

LOCAL_PACKAGE = "harness_gates"

NO_PY = "검사할 소스 없음"
NO_UI = "화면 소스 없음"
# 웹·화면 게이트는 프레임워크팩의 선언을 읽는다. 팩을 안 고르면 조용히 통과하지 않고 이 사유로 [SKIP] 이다.
NO_SERVER_PACK = "서버 프레임워크팩 미선택 — 프로파일 FRAMEWORK 에 적는다"
NO_UI_PACK = "화면 프레임워크팩 미선택 — 프로파일 FRAMEWORK 에 적는다"


def _print_style_reports(reports: list[str]) -> None:
    for report in reports:
        print(f"[REPORT] {report}")


def _print_sections(sections: list[Section]) -> int:
    """[FAIL] 머리에 slug 를 함께 찍는다.

    slug 는 이 하네스에서 게이트를 식별하는 이름이다. 동결 키도 로컬 섹션 이름도 slug 다. 그런데
    출력에만 없어서, `[FAIL]` 을 보고도 `harness_baseline.txt` 에 무엇을 적어야 하는지 알 수
    없었다. 관찰 기록(`kernel/trace.py`)이 파싱하는 출력 형식도 이 함수가 정본이다.
    """
    total = 0
    for slug, title, violations, skipped in sections:
        if skipped:
            grade, reason = skipped
            print(f"[{grade:<4}] {title} — {reason}")
        elif violations:
            total += len(violations)
            print(f"\n[FAIL] {title} ({slug}) — {len(violations)}건")
            for v in violations:
                print(f"   - {v}")
        else:
            print(f"[OK]   {title}")
    return total


def _under(files: list[Path], layer_name: str) -> list[Path]:
    prefix = profile.layer(layer_name)
    if not prefix:
        return []
    return [f for f in files if _rel(f).startswith(prefix)]


def _entry(slug: str, title: str, violations: list[str], ok: object, need: str) -> Section:
    """ok 가 거짓이면 [SKIP]. `위반 0건`과 `대상 0개`를 구분하는 것이 이 함수의 전부다.

    언어팩이 이 게이트를 '해당 없음'으로 선언했으면 그쪽이 우선이다 — 설정을 채우라고
    안내해봐야 그 언어에서는 채울 것이 없다.
    """
    unneeded = profile.not_applicable(slug)
    if unneeded:
        return (slug, title, [], ("N/A", unneeded))   # 출처 이름은 profile 에서 병합할 때 이미 붙어 있다
    return (slug, title, violations, None) if ok else (slug, title, [], ("SKIP", need))


def _syntax_section(slug: str, title: str, check: object, args: tuple,
                    ok: object, need: str, kind: str) -> Section:
    """구문 분석 결과(구문 사실)에 기대는 검사. `kind` 는 그 게이트가 읽는 사실의 종류다(`kernel/facts.py` 헤더 참고).

    선택한 언어의 분석기가 그 종류를 내지 못하면 **실행하지 않는다.** 파서 없이 돌리면 모든 파일이
    '파싱 실패' 위반이 되기 때문이다. 관용구 정규식 계열 검사는 언어팩의 `PATTERNS` 로
    바꿔 끼우므로 여기 오지 않는다. 여기 남은 것은 실제 파서가 필요한 검사뿐이다.
    확인 순서는 화면 린트(`_ui_entry`)와 같이 N/A, SKIP(볼 소스 없음), TOOL(분석기 없음), 판정이다.
    """
    unneeded = profile.not_applicable(slug)
    if unneeded:
        return (slug, title, [], ("N/A", unneeded))   # 출처 이름은 profile 에서 병합할 때 이미 붙어 있다
    if not ok:
        return (slug, title, [], ("SKIP", need))     # 볼 소스가 없으면 분석기도 필요 없다
    reason = facts.unavailable(kind)
    if reason:
        return (slug, title, [], ("TOOL", reason))
    return _entry(slug, title, check(*args), ok, need)   # type: ignore[operator]


def _framework_section(slug: str, title: str, check: object, args: tuple,
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
        return (slug, title, [], ("N/A", f"{server['NAME']}: 이 프레임워크에서 성립하지 않음"))
    return _syntax_section(slug, title, check, args, ok, need, "python")


def _ui_entry(slug: str, title: str, lint: linters.UiLint, ok: object, need: str) -> Section:
    """ESLint 에 맡긴 화면 린터 결과에서 slug 하나의 섹션을 만든다. 확인 순서는 N/A, SKIP(대상·설정 없음), TOOL(eslint 없음), 판정이다."""
    unneeded = profile.not_applicable(slug)
    if unneeded:
        return (slug, title, [], ("N/A", unneeded))
    if not ok:
        return (slug, title, [], ("SKIP", need))
    if lint.missing:
        return (slug, title, [], ("TOOL", lint.missing))
    return (slug, title, lint.found.get(slug, []), None)


def _linter_sections() -> list[Section]:
    """언어팩이 선언한 표준 린터에 검사를 맡긴 결과."""
    found: list[Section] = []
    for slug, title, violations, skipped in linters.sections():
        found.append((slug, title, violations, ("TOOL", skipped) if skipped else None))
    return found


def _need_layer(name: str) -> str:
    return f"설정에 {name} 폴더를 안 적었음"


def _need_symbol(name: str) -> str:
    return f"설정에 {name} 이름을 안 적었음"


def _kernel_sections(files: list[Path], ui_files: list[Path]) -> list[Section]:
    both = files + ui_files
    web = _under(files, "routes")
    vocab = profile.VOCAB
    settings = profile.FILES.get("settings")
    # 화면 검사 6종(10·17~20·42)은 ESLint 한 번 실행으로 나온다. 규칙 정본은 kernel/eslint.harness.mjs 고,
    # 파서와 대상 확장자는 화면 프레임워크팩이 준다. 팩이 없으면 돌리지 않고 [SKIP] 이다.
    ui_ok = ui_files and profile.UI
    ui_need = NO_UI if not ui_files else NO_UI_PACK
    lint = linters.run_ui_lint(ui_files) if ui_ok else linters.UiLint({}, "")
    server_need = NO_UI if not ui_files else NO_SERVER_PACK if not profile.SERVER else _need_layer("routes")

    return [
        # 맨 앞에 둔다. 프로파일 형식이 틀리면 아래 검사 전부가 대상 0건으로 조용히 통과하기 때문이다.
        _entry("profile_shape", "프로파일 형식", profile.PROFILE_ERRORS, profile.LOADED,
               "프로파일 없음"),
        _entry("line_limit", "파일 길이 상한", core.check_line_limit(files), files, NO_PY),
        _entry("header_path", "헤더 경로 주석", core.check_header_path_comment(files), files, NO_PY),
        _syntax_section("closures", "중첩 def(클로저)", core.check_closures, (files,), files, NO_PY,
                        "nesting"),
        _syntax_section("func_limit", "함수 길이 상한", core.check_func_length, (files,), files, NO_PY,
                        "functions"),
        _entry("type_checking_future", "TYPE_CHECKING↔future annotations 짝",
               core.check_type_checking_future(files), files, NO_PY),
        _entry("abbrev_names", "축약 이름 단독 대입", core.check_abbrev_names(files),
               files and vocab["abbrev_names"], "설정에 금지할 축약어를 안 적었음"),
        _entry("abbrev_prefixes", "축약 접두 식별자", core.check_abbrev_prefixes(both),
               both and vocab["abbrev_prefixes"], "설정에 금지할 축약 접두어를 안 적었음"),
        _entry("ui_jargon", "UI 라벨 금칙어", core.check_ui_jargon(ui_files),
               ui_files and vocab["ui_denylist"], "설정에 화면 금칙어를 안 적었음"),
        _entry("py_any", "Any 타입힌트", core.check_py_any(files), files, NO_PY),
        _syntax_section("type_hints", "공개 함수 타입힌트", core.check_type_hints, (files,), files, NO_PY,
                        "types"),
        _entry("secrets", "시크릿 토큰 하드코딩", core.check_secrets(both), both, NO_PY),
        _ui_entry("ts_any", "TS any 타입", lint, ui_ok, ui_need),
        _entry("env_access", "설정 밖 환경변수 조회", layers.check_env_access(files),
               files and settings, "설정에 환경변수 모듈을 안 적었음"),
        _framework_section("web_async", "await 없는 async 핸들러",
                           layers.check_web_async_no_await, (files,), web, _need_layer("web"), "ASYNC_HANDLER"),
        _entry("ssl_bypass", "전역 SSL 패치 호출 위치", layers.check_ssl_bypass_location(files),
               files and profile.symbol("ssl_bypass"), _need_symbol("ssl_bypass")),
        _framework_section("routes_error", "라우트 에러 응답 형식",
                           layers.check_routes_error_response, (files,),
                           _under(files, "routes") and profile.symbol("error_response"),
                           _need_symbol("error_response"), "ERROR_STATUS_KWARG"),
        _ui_entry("raw_fetch", "공용 래퍼 없는 fetch", lint, ui_ok, ui_need),
        _ui_entry("hex_literal", "프론트 색 리터럴", lint, ui_ok, ui_need),
        _ui_entry("responsive", "폰을 깨뜨리는 고정 폭", lint, ui_ok, ui_need),
        _ui_entry("browser_api", "브라우저 API 직접 호출", lint,
                  ui_ok and profile.ALLOWLIST["ui_platform"],
                  ui_need if not ui_ok else "설정에 브라우저 API 래퍼를 안 적었음"),
        _ui_entry("hash_nav", "해시 네비게이션 단일 기전", lint, ui_ok, ui_need),
        _entry("ui_logic_tests", "프론트 로직 테스트 짝",
               tests_pairing.check_ui_logic_test_pairing(ui_files), ui_files, NO_UI),
        _entry("ui_component_tests", "프론트 컴포넌트 테스트 짝",
               tests_pairing.check_ui_component_test_pairing(ui_files), ui_files, NO_UI),
        _entry("root_litter", "루트 직속 잡파일", placement.check_root_litter(),
               profile.ROOT_FILES, "설정에 루트 허용 파일을 안 적었음"),
        _entry("prompt_version", "프롬프트 버전 범프", prompt_version.check_prompt_version(),
               profile.VERSIONED_PROMPTS and prompt_version.ready(),
               "설정에 버전 관리 프롬프트 목록을 안 적었음" if not profile.VERSIONED_PROMPTS
               else "원격 기본 브랜치 미상 — 비교 기준이 없음"),
        _entry("test_pairing", "수집·계산 모듈의 행동 테스트 짝",
               tests_pairing.check_module_test_pairing(files),
               profile.BEHAVIOR_TESTED_ROOTS, "설정에 테스트 대상 폴더를 안 적었음"),
        _entry("ddl_types", "DDL 저장 타입 잘림", schema.check_ddl_lossy_types(files),
               _under(files, "schema"), _need_layer("schema")),
        _entry("api_array", "API 응답 배열 필드 옵셔널",
               api_types.check_api_array_optional(ui_files),
               ui_files and api_types.baseline_ready(),
               NO_UI if not ui_files else "배열 동결 파일 미생성 — harness_install.py 가 만든다"),
        _entry("orphan_api", "소비 UI 없는 API 라우트",
               orphan_api.check_orphan_api(files, ui_files),
               (_under(files, "routes") or _under(files, "web")) and ui_files and profile.SERVER,
               server_need),
        _syntax_section("undefined_const", "미정의 모듈 상수",
                        core.check_undefined_module_constants, (files,), files, NO_PY, "python"),
    ]


def _doc_sections(full: bool = True) -> list[Section]:
    """문서 게이트. full 이 거짓이면(`--file`) 레포 전체 REPORT 와 아키텍처 그림 대조(검사 48)를 뺀다. 둘 다 편집한 파일과 무관하다."""
    greenfield = profile.STAGE == "greenfield"

    # 새 프로젝트는 MD 가 코드보다 먼저 나온다 — plan 문서가 아직 없는 경로를 가리키는 게 정상
    # 순서다. 그 시기에 이걸 강제하면 첫 문서부터 막힌다. 파일이 생기면 mature 에서 잡힌다.
    refs = md_graph.check_md_path_refs()
    if greenfield and full:
        _print_style_reports(refs)
    map_exists = (ROOT / profile.HARNESS_MAP).exists()
    lessons = profile.LESSONS_DOC

    sections: list[Section] = [
        _entry("md_path_refs", "MD 경로 참조 실존", refs, not greenfield, "greenfield — 리포트로만"),
        _entry("md_orphans", "고아 MD(허브 도달 불가)", md_graph.check_md_orphans(),
               profile.HUBS, "설정에 문서 시작점을 안 적었음"),
        _entry("md_harness_map", "하네스 지도 대조", md_graph.check_harness_map(),
               (ROOT / ".claude").is_dir() and (map_exists or not greenfield),
               f"greenfield — {profile.HARNESS_MAP} 아직 없음"),
        _entry("agent_model", "에이전트 모델 정책", harness_self.check_agent_model_policy(),
               profile.AGENT_MODEL_POLICY, "설정에 담당 AI 모델 표를 안 적었음"),
        _entry("lessons_promotion", "사고 절 승격 상태", harness_self.check_lessons_promotion(),
               lessons and (ROOT / lessons).exists(),
               f"선언된 {lessons} 가 아직 없음" if lessons else "설정에 사고 기록 문서를 안 적었음"),
        _entry("md_fn_refs", "MD 함수 참조 실존", md_graph.check_md_fn_refs(),
               not greenfield, "greenfield — 문서가 코드보다 먼저다"),
    ]
    if not full:                        # 아키텍처 그림 대조(검사 48)는 그림과 소스 전체를 맞대는 검사라 --file 모드에는 비교 상대가 없다(중복 검사 34·35 와 같다)
        return sections
    # 그림과 실제 코드를 1:1 로 대조한다. 그림이 없는 greenfield 는 "아직 없음"으로 두고, 있으면 노드마다 소스 근거를 확인한다.
    hard, soft = arch_diagram.check_arch_diagram()
    _print_style_reports(soft)
    has_diagrams = bool(arch_diagram.diagrams())
    sections.append(_entry("arch_diagram", "아키텍처 그림 1:1 대조", hard,
                           has_diagrams or (arch_diagram.expected_nodes() and not greenfield),
                           "그릴 레이어·패키지가 아직 없음" if not arch_diagram.expected_nodes()
                           else f"greenfield — {diagram.DIAGRAM_DIR} 아직 없음"))
    if has_diagrams:
        sections += arch_diagram.engine_sections()
    for pair in profile.DOC_SYNC:
        title = f"문서↔코드 대조({pair['doc']}↔{pair['code']})"
        sections.append(_entry(f"doc_sync:{pair['doc']}", title,
                               md_graph.check_doc_sync(pair),
                               md_graph.doc_sync_ready(pair), "대조할 양쪽 실물이 아직 없음"))
    return sections


def _local_sections(files: list[Path], ui_files: list[Path]) -> list[Section]:
    """프로젝트가 자기 레포에 둔 게이트. `harness_gates/<이름>.py` 가 run(py, ui) 을 노출한다."""
    sections: list[Section] = []
    for name in profile.LOCAL_GATES:
        try:
            module = importlib.import_module(f"{LOCAL_PACKAGE}.{name}")
            results = module.run(files, ui_files)
        except Exception as exc:                     # 로드 실패를 조용히 넘기면 게이트가 사라진다
            sections.append((f"local:{name}", f"프로젝트 게이트 {name}",
                             [f"로드 실패 {exc.__class__.__name__}: {exc}"], None))
            continue
        for title, violations in results:
            sections.append((f"local:{name}", title, violations, None))
    return sections


def _build_sections(
    files: list[Path], ui_files: list[Path], include_md: bool, md_files: list[Path],
    full: bool = True,
) -> list[Section]:
    sections = _kernel_sections(files, ui_files)
    if include_md and files:            # 린터는 레포 전체를 보므로 --file 모드에선 건너뛴다
        sections += _linter_sections()
    # 중복은 파일 간 교차 비교라 대상이 전량일 때만 성립한다. `--file` 은 비교 상대가 없다.
    if include_md:
        decl, block = (duplication.check_duplication(files, ui_files)
                       if files or ui_files else ([], []))
        both = files or ui_files
        sections += [
            _entry("dup_decl", "선언 본문 중복(정본 재구현)", decl, both, NO_PY),
            _entry("dup_block", "블록 중복(선언 안 복붙)", block, both, NO_PY),
        ]
    sections += _local_sections(files, ui_files)
    if md_files:
        hard, soft = md_style.check_md_style(md_files)
        sections.append(("md_style", "MD 작성 규칙", hard, None))
        _print_style_reports(soft)
    if include_md:
        sections += _doc_sections(full)
    return sections


def _in_scope(f: Path) -> bool:
    """프로파일이 통째로 뺀 경로인가. 벤더 사본·참고 자료·픽스처가 여기 해당한다."""
    exclude = profile.SCOPE["exclude_all"]
    return not (exclude and _rel(f).startswith(exclude))


def source_files() -> tuple[list[Path], list[Path]]:
    """모든 게이트가 볼 (서버, 화면) 파일 목록. 하네스 자체 파일과 SCOPE 로 제외한 경로는 뺀다.

    확장자는 프로파일이 정한다. 커널에 `*.py` 를 박아두면 다른 언어 프로젝트에서 대상이
    0건이 되고, 그 상태가 화면에는 초록불로 보인다.
    """
    ui = profile.layer("ui")
    ui_files = ([f for f in app_code(*profile.UI_EXT, under=ui) if _in_scope(f)]
                if ui else [])
    files = ([f for f in app_code(*profile.SOURCE_EXT) if _in_scope(f) and f not in ui_files]
             if profile.SOURCE_EXT else [])
    return files, ui_files


def collect_all_violations() -> list[tuple[str, str]]:
    """동결할 대상, 즉 현재 모든 게이트 위반의 (slug, 파일) 쌍. 설치 스크립트가 쓴다.

    baseline 을 적용하지 않은 원본이다. 특정 파일에 속하지 않는 레포 전체 위반은 동결할 키가 없어
    빠지고, 그래서 설치 후에도 남는다. 사람이 직접 봐야 하는 것들이다.
    """
    files, ui_files = source_files()
    sections = _build_sections(files, ui_files, True, tracked_md_files())
    pairs = {(slug, path) for slug, _title, violations, _skip in sections
             for v in violations if (path := violation_path(v))}
    return sorted(pairs)


def tracked_md_files() -> list[Path]:
    return [f for f in tracked("*.md") if _in_scope(f) and md_style.style_target(_rel(f))]


def _single_file_lists(raw_path: str) -> tuple[list[Path], list[Path], bool, list[Path]]:
    """--file 모드: 대상 파일 하나를 (py, ui, 레포 전체 문서 검사 여부, MD 스타일 대상)으로 분류한다."""
    p = Path(raw_path).resolve()
    try:
        rel = _rel(p)                    # worktree 경로 접두를 뗀다. 안 떼면 `.claude/` 로 시작하는 경로가 되어
    except ValueError:                   # is_harness_own 에 걸리고, 작성 시점 검사가 경고 없이 통과한다
        return [], [], False, []
    exclude = profile.SCOPE["exclude_all"]
    if not p.exists() or (exclude and rel.startswith(exclude)):
        return [], [], False, []
    if p.suffix != ".md" and is_harness_own(rel):
        return [], [], False, []
    ui = profile.layer("ui")
    if ui and rel.startswith(ui) and any(fnmatch.fnmatchcase(rel, pat) for pat in profile.UI_EXT):
        return [], [p], False, []
    if any(fnmatch.fnmatchcase(rel, pat) for pat in profile.SOURCE_EXT):
        return [p], [], False, []
    if p.suffix == ".md":
        # 레포 전체 교차 검사는 정본 MD 를 편집했을 때만 다시 돌린다. 스타일 검사는 그 파일만 본다.
        style = [p] if md_style.style_target(rel) else []
        doc_exclude = tuple(profile.MD["doc_exclude"])
        canonical = not (doc_exclude and (rel.startswith(doc_exclude) or rel in doc_exclude))
        return [], [], canonical, style
    return [], [], False, []


def main(argv: list[str]) -> int:
    # Windows cp949 콘솔에서 위반 라인(유니코드 포함) 출력 크래시 방지
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(errors="replace")
    if profile.PROFILE_ERRORS:
        _print_sections([("profile_shape", "프로파일 형식", profile.PROFILE_ERRORS, None)])
        return 1
    if not profile.LOADED:
        print(f"[SETUP] {profile.PROFILE_FILE} 없음 — 프로젝트를 모르는 상태다. "
              f"레이어를 요구하는 게이트는 전부 [SKIP] 이다.")
    full = not (len(argv) >= 2 and argv[0] == "--file")
    if not full:
        files, ui_files, include_md, md_files = _single_file_lists(argv[1])
        if not files and not ui_files and not include_md and not md_files:
            include_md = False
    else:
        files, ui_files = source_files()
        include_md, md_files = True, tracked_md_files()
    sections = _apply_baseline(_build_sections(files, ui_files, include_md, md_files, full))
    sections += graph_checks.sections(ROOT, verify="--verify" in argv)
    total = _print_sections(sections)

    if "--verify" in argv and any(skip and skip[0] == "TOOL" for _, _, _, skip in sections):
        print("\n필수 검사 미검증 — 완료로 처리할 수 없다.")
        return 2
    violations = [v for _, _, found, _ in sections for v in found]
    if violations and all("needs_decision" in v for v in violations):
        print("[DECISION] 분류 변경안을 사용자에게 제안하고 응답을 기록하라.")
        return 3
    if total:
        print(f"\n총 {total}건 위반.")
        return 1
    print("\n전 게이트 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
