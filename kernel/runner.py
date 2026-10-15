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
등급을 가르는 판정 헬퍼와 건너뜀 사유는 `kernel/sections.py` 에 있다. 이 파일은 게이트를 나열하고 출력한다.

각 섹션은 slug 를 갖는다. slug 는 `harness_baseline.txt` 의 동결 키로도 쓰인다. 설치 시점에
이미 있던 위반을 (slug, 파일) 단위로 기록해 예외 처리하고, 모든 게이트가 통과한 상태에서 출발하게 하려는 것이다.
"""

from __future__ import annotations

import fnmatch
import importlib
import sys
from pathlib import Path

from kernel import component_graph, facts, graph_checks, linters, local_hooks, profile
# 러너를 거쳐 쓰도록 다시 내보낸다. trace 는 violation_path 를, 설치 스크립트는 BASELINE_FILE·load_baseline 을 쓴다.
from kernel.baseline import (BASELINE_FILE, apply_baseline as _apply_baseline,  # noqa: F401
                             load_baseline, violation_path)
from kernel.context import ROOT, _rel, app_code, is_harness_own, tracked
from kernel.gates import (api_types, core, duplication, harness_self, layers, md_graph, md_style, naming,
                          orphan_api, owners, placement, prompt_version, schema, tests_pairing, ui_styles)
from kernel.sections import (CONDITIONAL, NO_PY, NO_SERVER_PACK, NO_UI, NO_UI_PACK, Section, entry,
                             framework_section, linter_sections, need_layer, pack_section, syntax_section,
                             ui_entry)

LOCAL_PACKAGE = "harness_gates"


def _print_style_reports(reports: list[str]) -> None:
    for report in reports:
        print(f"[REPORT] {report}")


def _print_sections(sections: list[Section], compact: bool = False) -> int:
    """[FAIL] 머리에 slug 를 함께 찍는다.

    slug 는 이 하네스에서 게이트를 식별하는 이름이다. 동결 키도 로컬 섹션 이름도 slug 다. 그런데
    출력에만 없어서, `[FAIL]` 을 보고도 `harness_baseline.txt` 에 무엇을 적어야 하는지 알 수
    없었다. 관찰 기록(`kernel/trace.py`)이 파싱하는 출력 형식도 이 함수가 정본이다.
    `compact` 는 사유가 같은 건너뜀을 한 줄로 묶는다 — 설치 직후 사람이 읽는 출력용이고, 골든·관찰은 기본 형식을 본다.
    """
    total = 0
    grouped: dict[tuple[str, str], list[str]] = {}
    if compact:
        for _slug, title, _violations, skipped in sections:
            if skipped:
                grouped.setdefault(skipped, []).append(title)
    for slug, title, violations, skipped in sections:
        if skipped and compact:
            titles = grouped.pop(skipped, None)
            if titles:
                head = f"{len(titles)} checks — {skipped[1]}: " if len(titles) > 1 else ""
                print(f"[{skipped[0]:<4}] {head}{', '.join(titles) if head else titles[0] + ' — ' + skipped[1]}")
        elif skipped:
            grade, reason = skipped
            print(f"[{grade:<4}] {title} — {reason}")
        elif violations:
            total += len(violations)
            print(f"\n[FAIL] {title} ({slug}) — {len(violations)} found")
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


def _kernel_sections(files: list[Path], ui_files: list[Path], style_files: list[Path] | None = None) -> list[Section]:
    both = files + ui_files
    web = _under(files, "routes")
    vocab = profile.VOCAB
    settings = profile.FILES.get("settings")
    # 화면 검사 6종(10·17~20·42)은 ESLint 한 번 실행으로 나온다. 규칙 정본은 kernel/eslint.harness.mjs 고,
    # 파서와 대상 확장자는 화면 프레임워크팩이 준다. 팩이 없으면 돌리지 않고 [SKIP] 이다.
    ui_ok = ui_files and profile.UI
    ui_need = NO_UI if not ui_files else NO_UI_PACK
    lint = linters.run_ui_lint(ui_files) if ui_ok else linters.UiLint({}, "")
    # 스크립트 밖 스타일(스타일시트·템플릿)은 전체 실행에서만 텍스트로 본다 — 같은 slug 섹션에 합친다.
    styles = ui_styles.check_styles(style_files) if ui_ok and style_files else {}
    server_need = NO_UI if not ui_files else NO_SERVER_PACK if not profile.SERVER else need_layer("routes")

    return [
        # 맨 앞에 둔다. 프로파일 형식이 틀리면 아래 검사 전부가 대상 0건으로 조용히 통과하기 때문이다.
        entry("profile_shape", "Profile format", profile.PROFILE_ERRORS, profile.LOADED,
               "no profile"),
        entry("line_limit", "File length limit", core.check_line_limit(files), files, NO_PY),
        entry("header_path", "Header path comment", core.check_header_path_comment(files), files, NO_PY),
        syntax_section("closures", "Nested def (closure)", core.check_closures, (files,), files, NO_PY,
                        "nesting"),
        syntax_section("func_limit", "Function length limit", core.check_func_length, (files,), files, NO_PY,
                        "functions"),
        entry("type_checking_future", "TYPE_CHECKING↔future annotations pair",
               core.check_type_checking_future(files), files, NO_PY),
        entry("abbrev_names", "Bare abbreviated names", core.check_abbrev_names(files),
              files and vocab["abbrev_names"], CONDITIONAL["abbrev_names"]),
        entry("abbrev_prefixes", "Abbreviated identifier prefixes", core.check_abbrev_prefixes(both),
              both and vocab["abbrev_prefixes"], CONDITIONAL["abbrev_prefixes"]),
        entry("ui_jargon", "Banned UI label words", core.check_ui_jargon(ui_files),
              ui_files and vocab["ui_denylist"], CONDITIONAL["ui_jargon"]),
        entry("py_any", "Any type hints", core.check_py_any(files), files, NO_PY),
        syntax_section("type_hints", "Public function type hints", core.check_type_hints, (files,), files, NO_PY,
                        "types"),
        entry("secrets", "Hardcoded secret tokens", core.check_secrets(both), both, NO_PY),
        ui_entry("ts_any", "TS any type", lint, ui_ok, ui_need),
        entry("env_access", "Env var reads outside settings", layers.check_env_access(files),
               files and settings, "no settings module set in the profile"),
        framework_section("web_async", "Async handler without await",
                           layers.check_web_async_no_await, (files,), web, need_layer("web"), "ASYNC_HANDLER"),
        entry("ssl_bypass", "Global SSL patch call site", layers.check_ssl_bypass_location(files),
              files and profile.symbol("ssl_bypass"), CONDITIONAL["ssl_bypass"]),
        framework_section("routes_error", "Route response format",
                          layers.check_routes_error_response, (files,),
                          _under(files, "routes") and profile.symbol("error_response"),
                          CONDITIONAL["routes_error"], "ERROR_STATUS_KWARG"),
        ui_entry("raw_fetch", "fetch without the shared wrapper", lint, ui_ok, ui_need),
        ui_entry("hex_literal", "Frontend color literals", lint, ui_ok, ui_need, styles.get("hex_literal")),
        ui_entry("responsive", "Fixed widths that break phones", lint, ui_ok, ui_need, styles.get("responsive")),
        ui_entry("browser_api", "Direct browser API calls", lint,
                 ui_ok and profile.ALLOWLIST["ui_platform"],
                 ui_need if not ui_ok else CONDITIONAL["browser_api"]),
        ui_entry("hash_nav", "Single hash navigation mechanism", lint, ui_ok, ui_need),
        # 짝 대상 확장자는 화면팩이 선언한다 — 선언이 없으면 대상 0건 [OK] 가 아니라 [N/A] 다
        pack_section("ui_logic_tests", "Frontend logic test pairs", tests_pairing.check_ui_logic_test_pairing,
                     (ui_files,), ui_ok, ui_need, tests_pairing.ui_test_exts("LOGIC_EXT")),
        pack_section("ui_component_tests", "Frontend component test pairs",
                     tests_pairing.check_ui_component_test_pairing, (ui_files,), ui_ok, ui_need,
                     tests_pairing.ui_test_exts("COMPONENT_EXT")),
        entry("root_litter", "Stray files at repo root", placement.check_root_litter(),
               profile.ROOT_FILES, "no allowed root files set in the profile"),
        entry("prompt_version", "Prompt version bump", prompt_version.check_prompt_version(),
              profile.VERSIONED_PROMPTS and prompt_version.ready(),
              CONDITIONAL["prompt_version"] if not profile.VERSIONED_PROMPTS
              else "remote default branch unknown — nothing to compare against"),
        entry("test_pairing", "Behavior test pairs for collect/compute modules",
              tests_pairing.check_module_test_pairing(files),
              profile.BEHAVIOR_TESTED_ROOTS, CONDITIONAL["test_pairing"]),
        entry("ddl_types", "Lossy DDL storage types", schema.check_ddl_lossy_types(files),
              _under(files, "schema"), CONDITIONAL["ddl_types"]),
        entry("api_array", "Optional array fields in API responses",
               api_types.check_api_array_optional(ui_files),
               ui_files and api_types.baseline_ready(),
               NO_UI if not ui_files else "array baseline file missing — harness_install.py creates it"),
        entry("orphan_api", "API routes without a consuming UI",
               orphan_api.check_orphan_api(files, ui_files),
               (_under(files, "routes") or _under(files, "web")) and ui_files and profile.SERVER,
               server_need),
        syntax_section("undefined_const", "Undefined module constants",
                        core.check_undefined_module_constants, (files,), files, NO_PY, "python"),
        pack_section("naming", "Naming consistency", naming.check_naming, (files, ui_files), both, NO_PY,
                     profile.NAMING, "functions" if files else None),
        pack_section("single_owner", "One owner per shared capability", owners.check_single_owner,
                     (files, ui_files), both, NO_PY, profile.OWNED or profile.UI_OWNED),
    ]


def _doc_sections(full: bool = True) -> list[Section]:
    """문서 게이트. full 이 거짓이면(`--file`) 레포 전체 REPORT 와 문서↔코드 대조를 뺀다. 둘 다 편집한 파일과 무관하다."""
    # 새 프로젝트는 MD 가 코드보다 먼저 나온다 — plan 문서가 아직 없는 경로를 가리키는 게 정상 순서다. 그 시기에
    # 이걸 강제하면 첫 문서부터 막힌다. 첫 컴포넌트가 승인되면 코드가 생긴 것이므로 STAGE 를 손대지 않아도 졸업한다.
    greenfield = profile.STAGE == "greenfield" and not component_graph.has_components(ROOT)
    greenfield_why = "greenfield — report only until the first component is approved"
    refs = md_graph.check_md_path_refs()
    if greenfield and full:
        _print_style_reports(refs)
    map_exists = (ROOT / profile.HARNESS_MAP).exists()
    lessons = profile.LESSONS_DOC
    # 템플릿이 허브와 정책표를 미리 선언한다(자가 발전 기본값). 대상 문서가 아직 없는 설치(플러그인)는 [SKIP] 이고,
    # 허브 문서나 에이전트 폴더가 생기면 그 순간 켜진다.
    hubs_exist = any((ROOT / hub).is_file() for hub in profile.HUBS)
    agents_exist = (ROOT / harness_self.AGENTS_DIR).is_dir()

    sections: list[Section] = [
        entry("md_path_refs", "MD path references exist", refs, not greenfield, greenfield_why),
        entry("md_orphans", "Orphan MD (unreachable from hubs)", md_graph.check_md_orphans(),
              profile.HUBS and hubs_exist,
              "declared hubs do not exist yet" if profile.HUBS else "no doc entry points set in the profile"),
        entry("md_harness_map", "Harness map match", md_graph.check_harness_map(),
              (ROOT / ".claude").is_dir() and (map_exists or not greenfield),
              f"greenfield — {profile.HARNESS_MAP} does not exist yet"),
        entry("agent_model", "Agent model policy", harness_self.check_agent_model_policy(),
              profile.AGENT_MODEL_POLICY and agents_exist,
              f"{harness_self.AGENTS_DIR} does not exist" if profile.AGENT_MODEL_POLICY
              else "no agent model table set in the profile"),
        entry("lessons_promotion", "Incident promotion status", harness_self.check_lessons_promotion(),
              lessons and (ROOT / lessons).exists(),
              f"declared {lessons} does not exist yet" if lessons else "no lessons doc set in the profile"),
        entry("md_fn_refs", "MD function references exist", md_graph.check_md_fn_refs(),
              not greenfield, greenfield_why),
    ]
    if not full:                        # 문서↔코드 대조는 양쪽 실물을 맞대는 검사라 --file 모드에는 비교 상대가 없다(중복 검사 34·35 와 같다)
        return sections
    for pair in profile.DOC_SYNC:
        title = f"Doc↔code match ({pair['doc']}↔{pair['code']})"
        sections.append(entry(f"doc_sync:{pair['doc']}", title,
                               md_graph.check_doc_sync(pair),
                               md_graph.doc_sync_ready(pair), "both sides to compare do not exist yet"))
    return sections


def _local_sections(files: list[Path], ui_files: list[Path]) -> list[Section]:
    """프로젝트가 자기 레포에 둔 게이트. `harness_gates/<이름>.py` 가 run(py, ui) 을 노출한다."""
    sections: list[Section] = []
    for name in profile.LOCAL_GATES:
        try:
            module = importlib.import_module(f"{LOCAL_PACKAGE}.{name}")
            results = module.run(files, ui_files)
        except ModuleNotFoundError as exc:
            if exc.name not in (LOCAL_PACKAGE, f"{LOCAL_PACKAGE}.{name}"):
                raise
            # 템플릿이 선언한 로컬 게이트가 이 설치에 없다(플러그인 설치) — 설정 오류가 아니라 대상 없음이다
            sections.append((f"local:{name}", f"Project gate {name}", [],
                             ("SKIP", f"{LOCAL_PACKAGE}/{name}.py does not exist — local gates live in template installs")))
            continue
        except Exception as exc:                     # 로드 실패를 조용히 넘기면 게이트가 사라진다
            sections.append((f"local:{name}", f"Project gate {name}",
                             [f"load failed {exc.__class__.__name__}: {exc}"], None))
            continue
        for title, violations in results:
            sections.append((f"local:{name}", title, violations, None))
    return sections


def _build_sections(
    files: list[Path], ui_files: list[Path], include_md: bool, md_files: list[Path],
    full: bool = True, style_files: list[Path] | None = None,
) -> list[Section]:
    sections = _kernel_sections(files, ui_files, style_files)
    if include_md and files:            # 린터는 레포 전체를 보므로 --file 모드에선 건너뛴다
        sections += linter_sections()
    # 중복은 파일 간 교차 비교라 대상이 전량일 때만 성립한다. `--file` 은 비교 상대가 없다.
    if include_md:
        decl, block = (duplication.check_duplication(files, ui_files)
                       if files or ui_files else ([], []))
        both = files or ui_files
        # 서버 선언은 구문 사실의 함수 범위로 읽는다. 분석기가 없으면 대상 0건 [OK] 가 아니라 [TOOL] 이다.
        no_spans = facts.unavailable("functions") if files and profile.SYNTAX != "python" else ""
        dup_title = "Duplicate declaration bodies (reimplementation)"
        sections += [
            ("dup_decl", dup_title, [], ("TOOL", no_spans)) if no_spans else entry("dup_decl", dup_title, decl, both, NO_PY),
            entry("dup_block", "Duplicate blocks (copy-paste in declarations)", block, both, NO_PY),
        ]
    sections += _local_sections(files, ui_files)
    if full:                            # 프로젝트 훅의 자가 시험 — 편집한 파일과 무관하므로 전체 실행에서만 돈다
        sections += local_hooks.sections()
    if md_files:
        hard, soft = md_style.check_md_style(md_files)
        sections.append(("md_style", "MD writing rules", hard, None))
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


def style_files() -> list[Path]:
    """ui 레이어의 스타일시트와 템플릿 파일 — 화면 색·폭 검사의 스크립트 밖 대상(kernel/gates/ui_styles.py)."""
    ui = profile.layer("ui")
    return [f for f in app_code(*ui_styles.STYLE_EXT, under=ui) if _in_scope(f)] if ui else []


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
        _print_sections([("profile_shape", "Profile format", profile.PROFILE_ERRORS, None)])
        return 1
    if not profile.LOADED:
        print(f"[SETUP] {profile.PROFILE_FILE} missing — the project is unknown. "
              f"Every gate that needs a layer is [SKIP].")
    full = not (len(argv) >= 2 and argv[0] == "--file")
    styles: list[Path] = []
    if not full:
        files, ui_files, include_md, md_files = _single_file_lists(argv[1])
        if not files and not ui_files and not include_md and not md_files:
            include_md = False
    else:
        files, ui_files = source_files()
        styles = style_files()
        include_md, md_files = True, tracked_md_files()
    sections = _apply_baseline(_build_sections(files, ui_files, include_md, md_files, full, styles))
    sections += graph_checks.sections(ROOT, verify="--verify" in argv)
    total = _print_sections(sections, compact="--compact" in argv)
    violations = [v for _, _, found, _ in sections for v in found]
    decisions = [v for v in violations if "needs_decision" in v]
    if decisions:                       # [TOOL] 이나 다른 [FAIL] 이 함께 있어도 결정 요청은 가려지지 않는다
        print("[DECISION] Propose the classification change to the user and record the answer.")
    if "--verify" in argv and any(skip and skip[0] == "TOOL" for _, _, _, skip in sections):
        print("\nRequired checks unverified — cannot be treated as done.")
        return 2
    if decisions and len(decisions) == len(violations):
        return 3
    if total:
        print(f"\n{total} violations.")
        return 1
    # 끝줄은 사용자가 읽는 결론이다. 꺼진 검사를 세지 않고 "다 통과"라고 쓰면 [SKIP]≠통과 원칙이 끝줄에서 깨진다.
    checked = sum(1 for *_head, skip in sections if not skip)
    unchecked = sum(1 for *_head, skip in sections if skip and skip[0] == "SKIP")
    tail = f" · {unchecked} not checked ([SKIP] is not a pass — see the reasons above)" if unchecked else ""
    print(f"\n{checked} checks passed{tail}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
