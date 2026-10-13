"""Stop hook — 이번 브랜치에서 새로 추가된 화면 문구를 Haiku 가 감수한다.

정규식 금칙어 명단(프로파일 `ui_denylist`)은 등록된 단어만 잡는다. 새로 생긴 내부 용어나 줄임말은
나중에 명단에 추가하는 방식이라 늘 한발 늦다. 문구 품질은 명단만으로 다 판정할 수 없으므로 명단에 없는 것은 LLM 이
판정하고, 거기서 잡힌 단어는 명단에 추가해(명단은 늘기만 한다) 다음부터는 정규식이 먼저 잡게 한다.

동작:
1. 원격 기본 브랜치와 비교한 커밋된 변경과 아직 커밋하지 않은 변경의 diff 에서 ui 레이어의 **추가된 줄**만 모은다.
2. 프로파일 `UI_COPY["language"]` 의 언어로 문구를 뽑는다. 한·일·중처럼 문자로 문구를 가를 수 있는 언어는 문자열
   리터럴과 JSX 텍스트를, 라틴 문자 언어는 JSX 텍스트만 본다 — 라틴 문자 리터럴은 코드(`className`·경로)와 문자로
   가를 수 없다. 주석은 사용자에게 보이지 않으므로 스캐너로 제거해 판정에서 뺀다. 테스트 파일도 뺀다. 기대 문자열을
   "고치면" 테스트가 실제 코드와 어긋나기 때문이다.
3. 문구가 있으면 Haiku 를 한 번 호출해 감수한다. 같은 문구 집합은 해시 캐시를 써서 다시 호출하지 않는다.
   Stop 은 턴마다 실행되므로 캐시가 없으면 대기 시간과 비용이 턴마다 반복된다.
4. 위반이 있으면 exit 0 + `systemMessage` 로 사용자에게 경고만 하고 종료는 막지 않는다. LLM 판정은 직접 관측이 아니라 추론이고,
   추론에는 차단 권한을 주지 않는다(`dev/HARNESS.md` 「단계」). 이미 알려진 조어는 UI 라벨 금칙어 검사(검사 6)가 규칙대로
   막고, 여기서 새로 잡힌 단어는 그 명단에 등록해 다음부터 검사 6 이 막게 한다. 인프라 실패(CLI 없음,
   타임아웃, 파싱 실패), ui 레이어가 선언되지 않은 경우, 기본 브랜치를 알 수 없는 경우는 **통과 처리**한다. 문구 검사가
   인프라 문제로 세션을 붙잡아 두면 안 된다. 단 통과 처리했다는 사실은 같은 채널로 알린다(아무 알림 없이 넘어가지 않는다 —
   exit 0 의 stderr 는 아무도 읽지 않는다). 화면이 있는데 언어가 비어 있으면 감수가 꺼져 있다고 알린다 — 설정 빈칸은
   막을 이유가 아니라 알릴 이유다.

판정 기준 5가지는 프로젝트와 무관하게 쓰이므로 이 파일이 정본이다. 언어·업종 맥락·도메인 필수 용어는 프로파일 `UI_COPY` 에서 넣는다.
"""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import default_branch, notify, payload_sid, record  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

MODEL = "haiku"   # Claude Code 모델 별칭. 날짜가 박힌 ID 는 폐기되는 날부터 이 감수가 조용히 통과로 바뀐다
CALL_TIMEOUT_SEC = 90   # 훅 안에서 claude 를 다시 호출하면 콜드 스타트가 있다 — 원본 프로젝트에서 60초를 넘긴 적이 있다
MAX_STRINGS = 120
MAX_CHARS = 6000

# 문자로 문구를 가를 수 있는 언어. 표에 없는 언어(라틴 문자)는 코드와 문구를 문자로 가를 수 없어 JSX 텍스트만 본다.
SCRIPTS = {"ko": "가-힣", "ja": "ぁ-んァ-ヶ一-龥", "zh": "一-龥"}  # ko-ok: script classes that mark screen copy
NAMES = {"ko": "Korean", "ja": "Japanese", "zh": "Chinese", "en": "English"}
LATIN = "A-Za-z"
# JSDoc/블록 주석의 이어지는 줄. _strip_comments 는 줄 단위라 여러 줄 /** */ 의 2번째 줄부터는
# 주석인지 알아보지 못한다. diff 에는 그 중간 줄만 들어 있어 여는 `/*` 가 아예 없을 때도 있다.
_JSDOC_CONT = re.compile(r"^\s*\*")
# 템플릿 리터럴의 치환 자리. 코드가 그대로 문구로 잡히는 것을 막는다.
_TEMPLATE_EXPR = re.compile(r"\$\{[^}]*\}")
_PROMPT_HEAD = """You review user-facing {language} screen copy for {context}. Below are the strings added
in this change. Flag only **clear** violations — when in doubt, let it pass (this review runs at the end of
every turn, so over-flagging does more harm than missing one).

Violations:
1. Internal implementation terms shown to users — words only developers or operators know (pipeline, backfill, queue, raw, scope).
2. Abbreviations and jargon that make no sense when read aloud.
3. Slang, metaphors, chatty filler.
4. Stilted or translated-sounding phrasing that a native {language} reader would not write.
5. Text that is not a sentence or label when read aloud (missing particles, broken grammar).

Not violations: required domain terms{terms}, company and institution names, short noun labels ("Save", "Period", "Status"),
technically precise short notation, quotes of menu, tab and feature names that exist on screen.

Output exactly one JSON object: {{"violations": [{{"text": "the string", "reason": "why, one line",
"suggest": "replacement"}}]}} — with no violations, {{"violations": []}}.

Strings:
"""


def copy_patterns(language: str) -> tuple[re.Pattern[str] | None, re.Pattern[str], re.Pattern[str]]:
    """(리터럴, JSX 텍스트, 문구로 칠 최소 단어). 표에 없는 언어는 리터럴 패턴이 None 이다."""
    letters = SCRIPTS.get(language, LATIN)
    text = re.compile(rf">([^<>{{}}\n]*[{letters}][^<>{{}}\n]*)<")
    word = re.compile(rf"[{letters}]{{2,}}")
    if language not in SCRIPTS:
        return None, text, word
    literal = re.compile(rf"'([^'\n]*[{letters}][^'\n]*)'|\"([^\"\n]*[{letters}][^\"\n]*)\"|"
                         rf"`([^`\n]*[{letters}][^`\n]*)`")
    return literal, text, word


def _profile_ui() -> tuple[str | None, str | None, str, tuple[str, ...]]:
    """(ui 레이어 접두, 화면 언어, 업종 맥락, 도메인 용어). 프로파일을 못 읽으면 ui 레이어가 없는 것으로 본다."""
    try:
        from kernel import profile
    except Exception:
        return None, None, "", ()
    ui = profile.layer("ui")
    language = profile.UI_COPY.get("language")
    context = str(profile.UI_COPY.get("context") or "this product")
    terms = tuple(profile.UI_COPY.get("product_terms") or ())
    return ui, (str(language) if language else None), context, terms


def _run_git(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO)] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    return completed.stdout if completed.returncode == 0 else ""


def _strip_comments(line: str) -> str:
    """따옴표 밖의 // 이후와 /* */ 블록을 제거 — 주석 속 문구는 화면에 안 나간다."""
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        nxt = line[i:i + 2]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if nxt == "//":
            break
        if nxt == "/*":
            end = line.find("*/", i + 2)
            if end == -1:
                break
            i = end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _added_lines(base: str, ui: str) -> list[str]:
    # 테스트 파일은 화면에 나오지 않는다. it() 설명과 기대 문자열이 걸려서 그걸 "고치면"
    # 테스트가 실제 코드와 어긋난다. pathspec 으로 스캔에서 뺀다.
    paths = [ui, f":(exclude){ui}**/*.test.ts", f":(exclude){ui}**/*.test.tsx"]
    diffs = _run_git(["diff", "-U0", f"origin/{base}...HEAD", "--"] + paths) \
        + _run_git(["diff", "-U0", "HEAD", "--"] + paths)
    return [ln[1:] for ln in diffs.splitlines()
            if ln.startswith("+") and not ln.startswith("+++")]


def _candidate(text: str, word: re.Pattern[str]) -> str | None:
    """추출된 조각을 감수할 문구로 바꾼다. 감수 대상이 아니면 None.

    템플릿 치환(`${…}`)을 `{value}` 자리표시로 바꿔 **렌더된 모습에 가깝게** 넘긴다. 코드를
    그대로 보내면 감수자가 문법을 보고 "내부 구현 노출"로 판정하는데, 그건 고칠 것이 없는
    위반이라 세션만 붙잡아 둔다. 치환 자리를 지운 뒤에도 두 글자 이상 이어져야 문구다 —
    `${y}년 ${m}월` 에서 남는 조사·단위 조각은 감수할 문구가 아니다.
    """
    masked = _TEMPLATE_EXPR.sub("{value}", text).strip()
    return masked if word.search(_TEMPLATE_EXPR.sub(" ", text)) else None


def extract_strings(lines: list[str], language: str) -> list[str]:
    """추가된 코드 줄에서 그 언어의 사용자 노출 후보 문구를 추출한다(중복 제거·순서 유지)."""
    literal, text, word = copy_patterns(language)
    seen: dict[str, None] = {}
    for raw in lines:
        if _JSDOC_CONT.match(raw):
            continue
        line = _strip_comments(raw)
        if not word.search(line):
            continue
        for match in (literal.finditer(line) if literal else ()):
            if (found := _candidate(next(g for g in match.groups() if g is not None), word)):
                seen.setdefault(found)
        for match in text.finditer(line):
            if (found := _candidate(match.group(1), word)):
                seen.setdefault(found)
    return list(seen)


def _cache_path(strings: list[str]) -> Path:
    digest = hashlib.sha256("\n".join(sorted(strings)).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"ui_copy_gate_{digest}.json"


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _judge(strings: list[str], language: str, context: str, terms: tuple[str, ...]) -> list[dict]:
    """Haiku 를 한 번 호출해 감수하고 violations 리스트를 반환한다. 호출이나 파싱 실패는 호출하는 쪽에서 통과 처리한다."""
    term_note = f" ({', '.join(terms)})" if terms else ""
    prompt = _PROMPT_HEAD.format(language=NAMES.get(language, language), context=context, terms=term_note) \
        + "\n".join(f"- {s}" for s in strings[:MAX_STRINGS])[:MAX_CHARS]
    done = subprocess.run(["claude", "-p", prompt, "--model", MODEL],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=CALL_TIMEOUT_SEC)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[:200] or "claude CLI failed")
    data = json.loads(_strip_fence(done.stdout))
    violations = data.get("violations", [])
    return violations if isinstance(violations, list) else []


def main() -> None:
    ui, language, context, terms = _profile_ui()
    if not ui:
        sys.exit(0)                       # 화면 레이어가 없는 프로젝트 — 검사할 대상이 없다
    if not language:
        notify("[UI COPY GATE] UI copy review is off — set UI_COPY['language'] in harness_profile.py "
               "(ko · en · ja · zh) so new screen strings get reviewed.")
        sys.exit(0)
    base = default_branch()
    if base is None:
        sys.exit(0)                       # 원격 기본 브랜치를 알 수 없다 — diff 기준이 없다

    try:
        strings = extract_strings(_added_lines(base, ui), language)
    except Exception as exc:
        notify(f"[UI COPY GATE] Could not collect the diff ({exc}) — treated as pass")
        sys.exit(0)
    if not strings:
        sys.exit(0)

    cache = _cache_path(strings)
    violations = None
    if cache.exists():
        try:
            violations = json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            violations = None
    if violations is None:
        try:
            violations = _judge(strings, language, context, terms)
        except Exception as exc:
            notify(f"[UI COPY GATE] LLM review could not run ({exc.__class__.__name__}: {exc}) — treated as pass. "
                   f"{len(strings)} strings remain unreviewed.")
            sys.exit(0)
        try:
            cache.write_text(json.dumps(violations, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    if not violations:
        sys.exit(0)
    record("check_ui_copy", "ui_copy", sid=payload_sid(), msg=f"{len(violations)} found", level="warn")
    notify("\n".join([
        f"[UI COPY GATE] {len(violations)} possible violations in {len(strings)} new screen strings — "
        "fix them. Add the caught words to harness_profile.py VOCAB['ui_denylist'] and the UI label denylist check (check 6) blocks them from then on:",
        *(f"  - '{v.get('text', '?')}' — {v.get('reason', '')} → {v.get('suggest', '')}" for v in violations)]))
    sys.exit(0)                           # 경고 — LLM 의견으로 세션을 잠그지 않고, exit 1 의 "hook error" 로 보이지도 않는다


if __name__ == "__main__":
    main()
