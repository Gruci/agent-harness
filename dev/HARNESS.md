# dev/HARNESS.md — 하네스 지도

> 담는 것: 공용 검사 계약과 런타임별 훅·스킬 연결. 담지 않는 것: 각 항목의 정본 내용(→ `.claude/` 각 파일·`kernel/` 헤더)·세션 행동 규칙(→ `CLAUDE.md`)·이 프로젝트가 무엇인지(→ `PROJECT.md`). 읽는 시점: 하네스를 파악하거나 수정할 때.

하네스를 고치려면 먼저 하네스를 볼 수 있어야 한다. 이 파일이 그 눈이고, 구성이 바뀌면 같은
턴에 갱신한다. 빠뜨리면 검사 28이 실물과 대조해 잡는다.

## 공용 하네스 운영

공통 절차는 [작업 절차 허브](dev/workflows/README.md)가 정본이다.
각 에이전트의 진입 문서와 스킬은 공통 절차에 자기 도구만 연결한다.
Impeccable은 수정하지 않는 벤더 자산 한 벌을 두 어댑터가 함께 참조한다.

| 책임 | 계약 |
|---|---|
| 검사 판정 | `kernel/runner.py`가 양쪽에 같은 결과를 낸다 |
| 저장·종료 실행 | `kernel/hook.py`가 입력과 오류 등급을 공통 처리한다 |
| Claude 연결 | 기존 저장·종료 Python 훅이 공통 진입점을 호출한다 |
| Codex 연결 | `.codex/hooks.json`이 Bash 실행 전과 patch 후와 Stop에 공통 진입점을 호출한다 |
| 설치 진단 | `python -X utf8 harness_install.py --check-agents`로 누락과 배선 불일치를 검사한다 |

Codex에서는 프로젝트와 새 훅 정의를 런타임에서 신뢰해야 실행된다.
공식 CLI의 `/hooks`에서 확인하며 호스트 앱은 해당 앱의 훅 지원과 신뢰 설정을 확인한다.
파일 진단 통과는 실제 훅 활성화의 증거가 아니다.
근거는 [공식 Codex 훅 문서](https://learn.chatgpt.com/docs/hooks)다.

### 전역 자율 실행 초기화

`python -X utf8 setup_global_permissions.py --agent codex`가 Codex 전역 자율 실행을 설치한다.
`--agent both`는 양쪽 초기화를 수행하며 기존 무인자는 Claude 초기화와 호환된다.
Codex 경로는 `CODEX_HOME`을 우선하고 없으면 사용자 홈의 `.codex`를 사용한다.
도구 승인 정책은 `never`이며 샌드박스는 전체 접근을 사용한다.
새 권한 프로파일 형식이 이미 있으면 같은 의미의 전체 접근 프로파일을 사용한다.
전역 지침은 중요한 모호함의 확정과 구현 전 계획 승인에서만 질문하도록 정한다.
이미 받은 승인은 다시 요구하지 않는다.
설치 전 기존 파일을 백업하고 모델·인증·플러그인 설정을 보존한다.
`python -X utf8 setup_global_permissions.py --agent codex --check`는 쓰기 없이 설치 상태를 확인한다.
현재 세션에 고정된 제한이나 호스트가 강제한 설정은 사용자 전역 파일보다 우선한다.
설치 완료와 호스트 적용 완료를 구분하며 새 세션에서 확인한다.

### 저장·종료 계약

저장 훅은 이미 발생한 편집을 취소하지 않고 수정 피드백을 반환한다.
Codex patch의 모든 추가·수정·이동 대상은 payload의 작업 디렉터리 기준으로 검사한다.
저장과 종료 검사는 선택한 SOURCE_EXT와 UI_EXT를 같은 기준으로 수집한다.
종료 시에는 git 추적 파일과 아직 추가하지 않은 소스를 함께 검사한다.
사용자 결정 대기는 완료가 아니며 Stop은 질문 후 정상적으로 턴을 끝낼 수 있다.
다른 worktree를 검사할 때는 그 체크아웃의 프로파일과 커널을 사용한다.

공용화가 모든 도구 정책의 동일한 강제를 뜻하지 않는다.
셸 편집의 즉시 검사가 없는 경로도 종료 시 전체 검사를 통과해야 한다.

### 작업공간 판정 공유 — worktree 이름과 종료 시점 잔존 검사

worktree 이름·자리(⑧-2)와 종료 시점의 작업공간 검사(⑫~⑰)는 판정이 한 벌이다.
정본은 `kernel/worktree.py`(이름·자리·범위·머지 끝난 worktree)와 `kernel/workspace.py`(보드·git 원격·목업·과업 산출물)다.
Claude 훅은 페이로드·stderr·trace·exit 만 맡는 래퍼이고, Codex 는 `kernel/hook.py` 가 PreToolUse(Bash)와 Stop 에서 같은 판정을 부른다.
단계(차단·경고)는 판정이 정하고 채널만 런타임이 다르다.

| 런타임 | 차단 | 경고 |
|---|---|---|
| Claude | exit 2 + stderr | exit 1 + stderr — 사용자 화면에만 |
| Codex | exit 2 + stderr | exit 0 + `{"systemMessage": …}` — 차단이 섞인 턴에는 stderr 에 덧붙인다 |

Codex 에는 EnterWorktree 툴이 없어 `git worktree add` 만 대상이다.
도구 사용 전 권한과 나머지 Claude 전용 보조 훅(SessionStart·Read 다이어트·셸 쓰기·워크플로·UI 카피)은 런타임별로 유지한다.

## 구조

런타임별 훅이 공통 검사 진입점을 호출하고 커널은 프로파일을 통해 프로젝트 규칙을 읽는다.
프로젝트별 경로와 예외는 프로파일에서 정하며 실행 도구의 입력 형식은 어댑터에서 처리한다.

이 구조의 그림은 `docs/architecture/` 에 있다 — 상자마다 소스 파일·행 범위가 박혀 있고 검사 48 이 실물과 대조한다.

| 그림 | 무엇 | 열기 |
|:--|:--|:--|
| 구조 | 세션 → 훅·규칙·스킬 → 러너 → 게이트·팩·프로파일 → 관찰·테스트·엔진 | `docs/architecture/harness.architecture.html` |
| 훅 발화 순서 | 위 표 ①~⑱ 를 레인·단계로. 가이드 뷰 3개, `?present=1&play=1` 로 재생 | `docs/architecture/hooks.workflow.html` |
| Edit 한 번의 여정 | 저장 → ⑨ → 러너 → 게이트 → 관찰 → 피드백 → 재수정 | `docs/architecture/edit-trip.sequence.html` |
| 훅별 규칙 지도 | 어느 훅이 언제 무엇을 검사하나 — `settings.json` 배선과 게이트 목록에서 **생성**. 훅이 바뀌면 `python -X utf8 -m kernel.diagram rules` | `docs/architecture/rules.workflow.html` |

같은 이름의 `.svg` 가 README 에 실린다. 규약은 `dev/DIAGRAM.md`, 만드는 절차는 `arch-diagram` 스킬이다.

## Claude 훅 실행 순서

세션 시작부터 종료까지 시간순이다. **차단**은 exit 2 로 진행을 멈추고 모델에게 피드백을 준다.
**경고**는 exit 1 로 같은 메시지를 stderr 에 내되 멈추지 않는다. 그 stderr 는 사용자 화면에만 뜨고
모델은 읽지 않는다(Stop·PreToolUse·PostToolUse 공통) — 경고는 사용자 고지 수단이다.
어느 쪽을 쓰는지는 아래 「단계」가 정한다.

| # | 이벤트 | 훅 | 조건 | 결과 |
|---|--------|----|------|------|
| ① | SessionStart | `code-master.md` 주입 — 코딩 페르소나(단순성 우선·근본 원인·비타협 안전) | 항상 | 통과 |
| ② | SessionStart | git·origin 검사 | 저장소 아님 또는 origin 미설정 | 경고 문자열 |
| ③ | SessionStart | 프로파일 검사 | `harness_profile.py` 없음, 또는 `PROFILE_SCHEMA` 가 커널 요구치보다 낮음(새 항목 목록 고지) | 경고 문자열 |
| ④ | SessionStart | 인터프리터 검사 | python 또는 node 실행 불가 | 경고 문자열 |
| ⑤ | SessionStart | `git_staleness.py` | 항상 열린 과업 주입 + 기본 브랜치가 origin 보다 뒤면 정렬 (**startup 한정**) | 과업 목록 · ff-only 자동 정렬 |
| ⑥ | SessionStart | `check_maintenance.py` | 정비 임계치 초과 (**startup 한정**) | 밀린 정비 목록 |
| ⑦ | UserPromptSubmit | `check_context_growth.py` | transcript 가 임계 초과 | 경고 + `/clear` 권고 |
| ⑧ | PreToolUse(Read) | `check_context_diet.py` | 추정 토큰 초과인데 분할 없음 | **차단** |
| ⑧-1 | PreToolUse(Bash·PowerShell) | `check_bash_write.py` | 셸로 소스 쓰기·판정 exit 삼킴·병렬 중 공유 트리 git 변경 | **차단** |
| ⑧-3 | 〃 | `check_bash_write.py` | 트리 밖·의존성 디렉토리를 잇는 junction·symlink 생성 | **차단** |
| ⑧-2 | PreToolUse(EnterWorktree·Bash·PowerShell) | `check_worktree_name.py` — 판정 `kernel/worktree.py`, Codex 공유 | 새 worktree 이름에 `--<sid8>` 접미 없음 | **차단** |
| ⑧-2 | 〃 | `check_worktree_name.py` — 판정 `kernel/worktree.py`, Codex 공유 | worktree 이름 앞부분이 내 workboard 범위와 다름 (내 보드 파일 있을 때만) | **차단** |
| ⑧-4 | PreToolUse(Workflow) | `check_workflow_script.py` | 스크립트의 `agent()` 에 model 미지정 | **차단** |
| ⑧-5 | PreToolUse(Edit·Write·MultiEdit·NotebookEdit) | `check_workboard_overlap.py` | 다른 과업의 `손대는 곳` 글로브에 걸리는 파일을 편집 | 경고 (추론) — exit 0 JSON. `systemMessage` 로 사용자에게, `additionalContext` 로 모델에게 넘긴다. 후자는 문서화된 필드지만 실측 확인은 아직이다 |
| ⑨ | PostToolUse(Edit·Write·MultiEdit) | `check_file_rules.py` | 저장한 파일이 게이트 위반 | **차단** |
| ⑩ | PostToolUse(Edit·Write·MultiEdit) | `impeccable/scripts/hook.mjs` | 항상 | 통과 (UI 리마인더) |
| ⑪ | SubagentStop | `check_agent_return.py` | 반환이 임계 초과 | **차단** |
| ⑫ | Stop | `check_editing_lock.py` — 판정 `kernel/workspace.py`, Codex 공유 | `workboard/` 에 자기 `#sid` 과업 파일이 **머지 후에도** 잔존 (진행 중은 통과) | 경고 (추론) |
| ⑫-1 | 〃 | `check_editing_lock.py` — 판정 `kernel/workspace.py`, Codex 공유 | 주인 없는 과업 파일 — 머지됐고 브랜치가 origin·로컬 양쪽에 없음 | 경고 (추론) |
| ⑬ | Stop | `check_coding_rules.py` | 전 게이트 위반 잔존 | **차단** |
| ⑭ | Stop | `check_git_remote.py` — 판정 `kernel/workspace.py`, Codex 공유 | GitHub 원격 미설정 | **차단** + 만들 명령 제시 |
| ⑮ | Stop | `check_worktree_residue.py` — 판정 `kernel/worktree.py`, Codex 공유 | 머지 끝난 worktree 잔존 — upstream 이 자기 브랜치일 때만 push 이력으로 센다 | 경고 (추론) + 정리 순서 제시 |
| ⑯ | Stop | `check_mockup_residue.py` — 판정 `kernel/workspace.py`, Codex 공유 | `docs/tasks/mockup/` 에 판단 끝난 시안 잔존 | **차단** (`wip_` 예외) |
| ⑰ | Stop | `check_task_residue.py` — 판정 `kernel/workspace.py`, Codex 공유 | 보드가 빈데 `docs/tasks/` 루트에 산출물 잔존 (`wip_`·최근 24시간 수정분 예외 — 보드 행은 3단계에 등록하므로 계획 단계 세션을 유예가 덮는다) | **차단** |
| ⑱ | Stop | `check_ui_copy.py` | 브랜치에서 새로 추가된 ui 레이어 한글 문구(리터럴·JSX 텍스트, 주석·테스트 파일 제외)를 Haiku 1콜로 감수 — `ui_denylist` 명단 밖 신종 내부어·축약·구어를 잡는다. 같은 문구 집합은 해시 캐시로 재호출 없음, 인프라 실패·ui 레이어 미선언은 stderr 고지 후 통과 | 경고 (LLM 판정) |

⚠️ **셸 게이트의 매처는 셸을 실행하는 툴을 전부 담아야 한다.** 이 환경에는 `Bash` 와 `PowerShell` 두 개가 있고, `Bash` 만 걸어두면 같은 명령이 `PowerShell` 로 그냥 나간다 — 원류에서 게이트 네 개가 전부 그렇게 무력화된 채 머지됐다(같은 `git switch` 가 Bash 차단·PowerShell 통과). 두 툴의 입력 필드가 똑같이 `command` 라 훅 본문은 손댈 것이 없고, 빠지는 것은 매처 한 단어뿐이라 눈에 안 띈다. 검사 28 은 훅 이름의 존재만 보고 **매처 문자열은 못 본다** — 그래서 이 규칙은 산문이다. **셸 툴이 늘면 매처부터 늘린다.**

### 단계 — 차단이냐 경고냐는 판정 근거가 정한다

훅은 exit 코드로 세 단계를 낸다: **0 통과 · 1 경고(메시지만) · 2 차단.** 어느 단계를 쓸지는
심각도가 아니라 **판정 근거**가 정한다.

| 단계 | 근거 | 해당 훅 |
|------|------|---------|
| **차단**(2) | **직접 관측** — 검사기가 실제로 위반을 뱉었거나 파일이 실제로 거기 있다 | ⑧ ⑧-1 ⑧-2 ⑧-3 ⑧-4 ⑨ ⑪ ⑬ ⑭ ⑯ ⑰ |
| **경고**(1) | **추론** — git 상태로 "끝났을 것"을 추측하거나, 사람이 적은 글로브로 겹침을 짚거나, LLM 이 문구를 판정한다 | ⑫ ⑫-1 ⑮ ⑱ — ⑧-5 는 같은 급이지만 PreToolUse 라 exit 0 JSON 으로 낸다 |
| **통과**(0) | 판정 불능 · **모델이 지금 고칠 수 없는 조건** | 전부 |

커널 게이트가 "확실한 위반만 잡는다(오탐 0)"로 지키는 선을, 훅에서는 **끄는 대신 단계를 낮춰**
지킨다. 검출을 끄면 잔해가 안 보이므로 사용자에게는 매 턴 알리되 문은 안 잠근다. 경고의 stderr 는
모델에게 닿지 않으므로, 모델이 읽어야만 하는 조건이라면 경고가 아니라 차단이어야 한다 — 그리고
추론 판정에는 차단 권한을 주지 않는다. 이 둘 사이가 경고 훅의 자리다.

근거는 추론 계열 둘이 연달아 오판한 것이다(`dev/LESSONS.md` §19). ⑫ 는 진행 중 보드 행을 막아
세션을 잠갔고, ⑮ 는 갓 판 worktree 를 "머지 완료"로 뒤집어 **작업 중인 판을 지우라고** 요구했다.
차단이면 잘못된 지시를 따르거나 세션이 잠기거나 둘 중 하나다.
**틀릴 수 있는 판정에는 차단 권한을 주지 않는다.**

⑱ 도 같은 계열이다. Haiku 의 문구 판정은 의견이지 관측이 아니다 — 알려진 조어는 검사 6 이
결정론적으로 막고, 명단 밖 신종은 경고로 올려 명단 등재를 유도한다. 의견으로 세션을 잠그지 않는다.

### 실패 시 방향 — 훅 오작동과 규칙 위반은 다른 사건이다

전자로 차단하면 복구 수단이 차단된 그 툴이라 세션이 잠긴다.

| 상황 | 방향 | 이유 |
|------|------|------|
| 훅 페이로드 파싱 실패 | 비차단 경고(exit 1) | Edit·Bash 전면 차단은 훅을 고칠 수단까지 막는다 — ⑨ 의 복구 경로가 Edit 자기 자신을 지난다 |
| 검사기 30초 무응답 | 비차단 경고(exit 1) | 검사기가 느린 것과 코드가 틀린 것은 다른 사건이다 |
| 검사기 자체 크래시(트레이스백, `[FAIL]` 없음) | ⑨ 비차단 경고(exit 1) · ⑬ 차단(exit 2) — 둘 다 "규칙 위반"이 아니라 "검사 불능"으로 말한다 | 위반으로 포장하면 모델이 트레이스백을 고칠 코드로 읽고 멀쩡한 파일을 되돌린다. 고칠 대상은 커널이다 |
| 규칙 위반 판정 | **차단**(exit 2) | 판정이 나온 경우다 |
| `session_id` 식별 불가 | 작업 소유권 추론만으로 차단하지 않음 | 남의 행을 삭제할 권한으로 해석하지 않는다 |
| 죽은 행 판정 불능 | 통과 | 보드 오탐은 종료 데드락이다 |
| 에이전트 반환문 미발견 | 통과 | 전 에이전트 차단이 더 위험하다(⑪ fail-open) |

작성 시점 검사(⑨)가 쉬어도 Stop 훅 ⑬ 이 세션 끝에 전량으로 받는다 — 이중 게이트라
비차단이 구멍이 되지 않는다.

**모델이 지금 고칠 수 없는 조건은 통과시킨다.** 차단은 "고쳐라"는 신호인데 고칠 수단이 없으면
신호가 아니라 벽이다. 머지 전 보드 행이 그랬다 — 지우는 것이 곧 거짓 완료 보고라 선택지가 없었다.
`stop_hook_active` 로 재차단만 빠져나가는 우회는 쓰지 않는다. 조건은 그대로 둔 채 입만 막는
것이라 다음 사람이 왜 막혔는지도 왜 안 막히는지도 못 읽는다. 훅이 도는 건 조건이 참이기
때문이고, 조건이 틀렸으면 조건을 고친다.

**차단·경고하는 훅은 막을 때마다 관찰을 남긴다.** 기록 모듈은 `kernel/trace.py`,
실물은 `harness_trace.jsonl` 이고 커밋한다. 기록이 실패해도 차단은 계속된다 — 관찰은 차단보다
항상 덜 중요하다. 같은 세션의 같은 차단은 한 번만 쌓인다. Stop 훅은 턴마다 발화해서, 안 그러면
위반 하나가 다섯 줄이 되어 빈도 집계가 통째로 거짓이 된다.
⑦ 은 배선하지 않았다. 게이트가 아니라 세션 위생 경고라 게이트 조정의 근거가 되지 않는다.
훅은 기록을 `_hookio.record` 로 남긴다. 커널을 못 읽어도 예외를 내지 않는 위임이다.
훅 명령은 전부 `python -X utf8` 로 등록한다. 빠지면 Windows cp949 에서 한글 출력이 `UnicodeEncodeError` 로 훅을 죽이고, exit 1 은 통과라 차단 훅이 조용히 꺼진다.

⑤⑥ 만 `startup` matcher 로 분리돼 있다. `/clear` 와 compact 마다 `git pull` 과 정비 판정이
다시 도는 것을 막기 위해서다.

### 임계 상수 — 값의 정본은 코드, 여기엔 왜 그 값인지만

| 상수 | 값 | 정의 | 근거 |
|------|-----|------|------|
| `LIMIT_TOKENS` | 16,000 | `check_context_diet.py` | 정리 후 최대 정본 MD 는 통과, 수십 KB 덤프는 차단하는 지점 |
| `CHUNK_LIMIT_LINES` | 500 | 〃 | 분할 읽기 탈출구 |
| `MAX_RETURN_CHARS` | 20,000 | `check_agent_return.py` | 상세 반환은 허용, 파일 전문 덤프는 차단 |
| `WARN_BYTES` | 15,000,000 | `check_context_growth.py` | transcript 는 실컨텍스트의 3~5배 프록시 — 1M 의 3분의 1 지점 |
| `MAX_LINES` | 400 | `kernel/gates/core.py` | 파일 단일 책임 하한선 |
| `MAX_FUNC_LINES` | 80 | 〃 | 파일 상한이 못 보는 축 — 함수 단일 책임 |
| `FRESH_SEC` | 86,400 | `kernel/workspace.py` | 계획 단계(보드 행 없음) 세션의 갓 쓴 산출물 유예 — 하루 지연은 오독 방지 목적을 안 흔든다 |

토큰 추정식은 ASCII 4자당 1토큰, 그 외 1자당 1토큰이다. 한글이 UTF-8 3바이트라 바이트로
재면 3배 과대평가된다.

⑭ 는 막기만 하지 않고 **무엇을 하면 되는지 완성된 명령으로 준다.** `gh` 가 인증돼 있으면
계정과 폴더 이름을 이미 알기 때문에 사용자에게 물을 게 없다. 인증이 없을 때만 질문이 남는다.
레포는 항상 `--private` 로 만든다 — 공개 발행은 되돌리기 어려워 사람이 정할 일이다.

## 게이트

판정 정본은 `kernel/gates/`이며 진입점은 `kernel/runner.py`다.
기술 검사 경로는 `harness_profile.py`의 CHECK_PATHS로 정한다.
업무 분류와 의존 관계는 [컴포넌트 계약](COMPONENTS.md)이 정본이다.

| # | 게이트 | slug | 무엇을 막나 |
|---|--------|------|-------------|
| 1 | 파일 길이 상한 | `line_limit` | 단일 책임을 잃은 파일 |
| 2 | 중첩 def | `closures` | 테스트할 수 없는 숨은 로직 |
| 4 | 축약 이름 | `abbrev_names` | 내부 코드가 이름으로 새는 것 |
| 5 | 축약 접두 | `abbrev_prefixes` | 〃 |
| 6 | UI 라벨 금칙어 | `ui_jargon` | 사용자에게 노출되는 조어 |
| 7 | py Any | `py_any` | 타입으로 게이트 때우기 |
| 8 | 공개 함수 타입힌트 | `type_hints` | 문서화되지 않은 모듈 경계면 |
| 9 | 시크릿 토큰 | `secrets` | 실키 하드코딩 |
| 10 | TS any | `ts_any` | 타입체커 strict 우회 — **ESLint 위임** |
| 12 | 설정 밖 환경변수 | `env_access` | 환경변수 읽는 지점이 흩어지는 것 |
| 13 | await 없는 async | `web_async` | 비동기인 척하는 동기 핸들러 |
| 15 | 전역 SSL 패치 위치 | `ssl_bypass` | 검증 우회가 아무 데서나 켜지는 것 |
| 16 | 라우트 에러 응답 | `routes_error` | 에러 형식이 라우트마다 다른 것 |
| 17 | 공용 래퍼 없는 fetch | `raw_fetch` | 캐시·에러 처리 없는 직접 호출 — **ESLint 위임** |
| 18 | 프론트 색 리터럴 | `hex_literal` | 색 하드코딩 (rgb·hsl 우회 포함) — **ESLint 위임** |
| 19 | 고정 폭 | `responsive` | 폰을 깨뜨리는 px 폭과 `100vw` — **ESLint 위임** |
| 20 | 브라우저 API 직접 호출 | `browser_api` | 앱 이식 때 교체 범위가 퍼지는 것 — **ESLint 위임** |
| 22 | 행동 테스트 짝 | `test_pairing` | 깨져도 아무도 모르는 수집·계산 모듈 |
| 23 | DDL 저장 타입 | `ddl_types` | 소스 정밀도를 못 담는 컬럼 |
| 24 | API 배열 옵셔널 | `api_array` | 배포 시차로 undefined 가 도착하는 것 |
| 25 | MD 작성 규칙 | `md_style` | 의미가 뭉개진 문서 |
| 26 | MD 경로 참조 | `md_path_refs` | 삭제·리네임 후 남은 유령 경로 |
| 27 | 고아 MD | `md_orphans` | 허브에서 도달 못 하는 문서 |
| 28 | 하네스 지도 | `md_harness_map` | 이 파일과 실물의 어긋남 — 양방향(빠진 실물·지도에만 남은 유령 행) |
| 29 | 에이전트 모델 정책 | `agent_model` | frontmatter 와 정책표의 드리프트 |
| 30 | 사고 절 승격 상태 | `lessons_promotion` | 사고를 적고 판단을 미루는 것 |
| 31 | 소비 UI 없는 API 라우트 | `orphan_api` | 화면이 없어 사용자에겐 존재하지 않는 기능 |
| 32 | 미정의 모듈 상수 | `undefined_const` | import 는 통과하고 호출 시점에 터지는 이름 |
| 33 | MD 함수 참조 실존 | `md_fn_refs` | 개명 후 MD 에 남은 유령 함수 |
| 34 | 선언 본문 중복 | `dup_decl` | 이름만 갈린 정본 재구현 |
| 35 | 블록 중복 | `dup_block` | 함수로 안 뽑힌 복붙 |
| 36 | 헤더 경로 주석 | `header_path` | 파일 이사 후 남은 옛 경로 주석 |
| 37 | 함수 길이 상한 | `func_limit` | 파일 400줄 상한이 못 보는 축 — 한 파일에 400줄 함수 하나 |
| 38 | TYPE_CHECKING 짝 | `type_checking_future` | future annotations 없는 3.11 NameError — 로컬 초록·CI 파열 |
| 42 | 해시 네비 단일 기전 | `hash_nav` | 이벤트를 안 내는 History API 혼용 — 주소만 바뀌고 화면이 안 따라온다 — **ESLint 위임** |
| 43 | 프론트 로직 테스트 짝 | `ui_logic_tests` | tsc·빌드가 못 잡는 값 오류 — export 함수 .ts |
| 44 | 프론트 컴포넌트 테스트 짝 | `ui_component_tests` | 〃 — 렌더 테스트 없는 .tsx |
| 45 | 루트 직속 잡파일 | `root_litter` | 확장자 불문 루트 덤프·메모 — 미추적 커밋 후보 포함 |
| 46 | 프롬프트 버전 범프 | `prompt_version` | 본문만 바뀐 LLM 프롬프트 — 산출물 판정 근거 소실 |
| 47 | 프로파일 형식 | `profile_shape` | 설정 이름 오타·튜플 자리의 문자열 — 예외 없이 게이트 대부분이 대상 0건으로 조용히 초록불이 된다 |
| 48 | 아키텍처 그림 1:1 대조 | `arch_diagram` · `arch_diagram_engine:<파일>` | 코드 어디인지 증명 안 된 노드, 이름 바꾸고 안 고친 그림, 렌더 안 한 정본. 엔진 위임분은 영수증 해시가 정본과 같으면 재호출 없이 OK, 아니면 node 없을 때 `[TOOL]` — 통과가 아니다. 전량 모드 전용(34·35 와 같다). 정본은 `dev/DIAGRAM.md` |

문서↔코드 대조(`doc_sync`)는 프로파일의 `DOC_SYNC` 가 정의한 만큼 늘어난다.

언어팩이 선언한 린터는 `정적 분석(<slug>)` 섹션(`lint:<slug>`)으로 찍힌다. 도구가 없으면 `[TOOL]` 이고,
레포 전체를 보는 도구라 `--file` 모드에선 돌지 않는다. 정본은 `kernel/linters.py` 다.

이 레포 전용 게이트는 `harness_gates/<이름>.py` 에 두고 `LOCAL_GATES` 로 켠다. 번호 표에는
넣지 않는다 — 그 표의 정본은 `kernel/gates/` 다.

| 로컬 게이트 | 무엇을 막나 |
|---|---|
| `edit_surface` | 면제·제외 목록 증가. 게이트를 무르게 만드는 제일 싼 경로다 |
| `archive_not_shipped` | 배포본(master)에 `docs/tasks/archive/` 산출물이 추적되는 것. 로컬 보관은 허용, git 추적만 막는다 — clone 해 간 프로젝트는 자기 archive 를 커밋하는 게 맞으므로 커널이 아니라 여기 산다 |

`edit_surface` 의 동결본은 `harness_surface.txt` 이고 다른 래칫과 같이 **감소만 허용**한다.
회고가 판정을 사람에게 맡기는 동안 이 문이 열려 있으면, 루프는 규칙을 고치는 대신 면제를
늘리는 쪽으로 수렴한다.

예외의 종류는 둘이고 넣을 곳이 다르다. **allowlist 는 사유 있는 영구 예외**다 — 래퍼 정본
자신처럼 규칙의 대상이 아닌 것. **baseline 은 리팩토링이 소거할 부채**라 줄어들기만 한다.
이 구분이 없으면 부채가 영구 예외가 된다.
기존 baseline 단위는 게이트와 파일이므로 같은 파일에 추가된 새 위반도 숨길 수 있다.
설치는 현재 위반을 자동 동결하지 않는다.
컴포넌트 그래프 검사는 기존 파일 baseline으로 면제할 수 없다.

프로파일 서식 오류는 실행 전에 보고한다.
컴포넌트 분류와 공개 계약 검사가 첫 코드의 위치와 허용 의존 관계를 확인한다.

34·35 는 **전량 모드 전용**이다. 파일 간 교차 비교라 작성 시점 `--file` 에는 비교할 상대가 없다.
동결본은 `dup_decl_baseline.txt`·`dup_block_baseline.txt` 이고 다른 래칫과 같이 감소만 허용한다.
키가 내용 해시가 아니라 **정렬된 파일 목록**인 이유는 해시로 얼리면 한 줄만 고쳐도 키가 빗나가
동결이 조용히 풀리기 때문이다. 현재 키 전량은 `python -X utf8 -m kernel.gates.duplication` 이 찍는다.

34 는 나머지와 성격이 다르다. 다른 게이트는 전부 **사고가 난 뒤에** 생겼다 — 누가 눈치채야 규칙이
하나 늘었다는 뜻이다. 34·35 는 그 앞단이라 어느 정본을 우회했는지 모르는 채로 "같은 것이 두 곳에
있다"만 본다. 하네스가 발견을 사람에게 맡기지 않는 첫 게이트다.

**화면 게이트 6종(10·17~20·42)은 판정을 ESLint 에 위임한다.** 정본은 `kernel/eslint.harness.mjs`
하나이고 러너가 npm 프로젝트(`UI_NPM_DIR`, 기본은 ui 레이어 첫 세그먼트)의 `node_modules/.bin/eslint`
로 돌린다. 줄 정규식은 문자열과 코드를 구분하지 못했다 — 주석 속 색이 걸리고 여러 줄 표현은 빠졌다.
실행 파일이 없으면 여섯이 `[TOOL]` 이다 — `npx --no-install` 로 부재를 판정하면 npm 오류가 0건으로
읽혀 무음 통과라 파일 실존으로 본다. 면제(`ALLOWLIST`·admin·토큰 정본)와 탈출 주석(`any-ok`·`px-ok`·
`web-ok`)은 정규식 시절 그대로다. 골든 픽스처에 도구가 없으면 `[TOOL]` 상태 자체를 비교하며 성공으로 판정하지 않는다.

검출 자체는 `tests/fixtures/uilint` 로 자체 테스트가 증명한다.

## 컴포넌트 그래프와 사용자 결정

[컴포넌트 계약](COMPONENTS.md)이 분류와 승인 기록의 정본이다.
[작동 예시](../examples/harness-reference/README.md)는 한 스택의 검증 사례이며 기본 제품 스택이 아니다.
AI는 미분류 변경을 구체적인 제안으로 사용자에게 알린다.
실제 대화 답변을 변경안에 기록하며 호스트 전용 알림 API를 요구하지 않는다.
로컬 기록 검사는 일관성을 확인하며 사용자 신원을 인증하지 않는다.

기존 숫자 게이트 목록과 별도로 그래프 검사는 이름으로 식별한다.

| 검사 이름 | 책임 | 판정 정본 |
|---|---|---|
| graph_schema | 그래프 서식과 참조 유효성 | `kernel/component_graph.py` |
| component_classification | 제품 코드의 단일 소유자와 역할 | `kernel/gates/components.py` |
| graph_approval | 제안과 실제 대화 결정 기록의 일치 | `kernel/graph_workflow.py` |
| component_dependencies | 허용 의존과 공개 계약 | `kernel/gates/context_api.py` |
| component_syntax | 분석할 수 없는 구문의 미검증 표시 | `kernel/gates/context_api.py` |
| graph_projection | 정본과 생성 지도의 일치 | `kernel/feature_map.py` |
| port_contracts | 선언한 포트의 실제 실행 계약 | `kernel/port_contracts.py` |
| port_tools | 포트 검사를 실행하지 못한 원인 | `kernel/port_contracts.py` |

포트를 선언한 경계만 대역과 실행 계약을 요구한다.
대역의 이름만 확인하지 않고 실제 계약 테스트를 실행한다.
검사기는 정본이나 제안 상태를 수정하지 않는다.
제안과 알림 상태 변경은 워크플로가 담당한다.

## Workflow 툴

결정론적 팬아웃이 필요할 때 쓰는 별도 경로다. Agent 툴 스폰이 기본이고, 이쪽은 루프·조건·
단계 통과를 스크립트로 고정해야 할 때만 고른다.

**계약 정본은 `.claude/agents/orchestrator.md` §4-1 이다.** 넷 중 model 명시만 ⑧-4 가 기계로
막고 나머지 셋(격리 금지·백그라운드 금지·resume 용도 한정)은 산문이다.

이 경로가 규약 없이 쓰이면 하네스의 모델 라우팅·격리·복구 규칙이 **하나도 적용되지 않는다.**
원류에서 그렇게 한 번 돌았고 그 세션의 워커 51개 중 14개가 결과 없이 죽었다(`dev/LESSONS.md` §20).

## 등급

| 등급 | 뜻 | 사람이 할 일 | exit |
|------|-----|-------------|------|
| `[OK]` | 검사했고 위반 0건 | 없음 | 0 |
| `[SKIP]` | 설정·대상이 없어 못 함 | 프로파일을 채우면 켜진다 | 0 |
| `[N/A]` | 이 언어에서 규칙이 성립 안 함 | **없음 — 손실이 아니다** | 0 |
| `[TOOL]` | 외부 도구나 구문 분석기가 검사하지 못함 | 도구와 분석 범위를 확인한다 | --verify에서 2 |
| `[FAIL]` | 강제 위반 | 고친다 | 1 |
| `[REPORT]` | 연성 신호. 오탐 여지가 있어 합산하지 않는다 | 판단 | 0 |
| `[DECISION]` | 새 분류나 경계에 사용자 결정 필요 | AI의 제안에 답한다 | 3 |

필수 검사를 수행하지 못하면 `--verify`는 완료 성공을 반환하지 않는다.
결정 대기의 종료 코드 3은 완료 허용이 아니라 사용자 질문 상태다.
Stop은 제안을 알리고 정상 대기를 허용하며 독립 작업은 계속할 수 있다.

`[OK]` 와 `[SKIP]` 을 가르는 것이 이 하네스의 핵심이다. 이전 세대는 레이어 이름이 안 맞아
대상이 0개인데도 `[OK]` 로 찍어, 지켜주지 않는 게이트를 지켜준다고 믿게 만들었다.

전역 `[REPORT]`(경로 참조·revision 이후 바뀐 원류)는 Stop 전량 모드에서만 찍는다. 작성 시점(`--file`)엔
편집한 MD 자신의 밀도 신호만 나온다 — 편집과 무관한 신호 수십 줄을 매번 보여주면 모델이 출력 자체를
안 읽게 되고, 그건 대상 0건 `[OK]` 와 같은 실패다.

## 언어팩

하네스의 Python 실행 환경은 제품 언어를 결정하지 않는다.
LANG을 선택하기 전에는 소스 확장자와 구문 분석을 임의로 Python으로 채우지 않는다.
새 프로젝트는 스택 미정 서식 하나에서 시작하며 [조립 절차](workflows/harness-assembly.md)를 따른다.
언어팩은 소스 확장자와 관용구 및 위임할 도구를 선언한다.
알 수 없는 팩 이름이나 깨진 팩은 설정 오류로 보고한다.
구문 분석기를 지원하지 않는 언어는 미검증으로 남긴다.
외부 도구의 비정상 종료를 빈 진단 목록만으로 성공 처리하지 않는다.

## 아키텍처팩

언어팩과 같은 골격을 아키텍처 축에 복제한 것이다. 프로파일의 `ARCH` 한 줄이
`kernel/archs/<이름>.py` 를 고르고, 거기 선언된 `NOT_APPLICABLE`(성립하지 않는 게이트와
사유)이 따라온다. 화면 없는 서비스의 UI 게이트가 `[SKIP]`(설정을 안 채움)이 아니라
`[N/A]`(아키텍처상 채울 것이 없음)로 찍히게 하는 것이 존재 이유다.

| 팩 | 뜻 | `[N/A]` 로 도는 것 |
|----|----|----|
| `web_layered` | 화면+서버 풀스택 | 없음 — 전 게이트 성립 |
| `backend_only` | 서버는 있고 화면이 없다 | 화면 게이트 7종 — 6·10·17~20·24 |
| `headless` | 웹도 화면도 없다 — 배치·CLI·라이브러리 | 위 7종 + 웹 2종(13·16). 31·42~44 는 어느 팩에도 없어 화면 경로가 비면 `[SKIP]` 으로 찍힌다 |

- 로더는 `kernel/arch.py`. 같은 이름을 `profiles/arch/<이름>.py` 에 두면 프로젝트 것이 이긴다.
- `ARCH` 미선언이면 아무것도 `[N/A]` 로 돌리지 않는다 — 도입 전 프로파일의 동작 그대로다.
- N/A 사유 병합은 언어팩 → 아키텍처팩 → 프로파일 순이고 나중이 이긴다. 출처 접두(`go:`·`headless:`)는
  `kernel/profile.py` 병합 시점에 붙는다 — 러너는 그대로 찍는다.
- 게이트 판정 코드는 옮기지 않았다. 팩은 선언이고 판정은 `kernel/gates/` — 언어팩과 같은 경계다.
- DB 계열 게이트는 어느 팩에도 없다 — 배치·라이브러리도 DB 를 가질 수 있어 "정의상 부재"가 아니다.
  프로젝트별 부재는 프로파일 `NOT_APPLICABLE` 이 담당한다.

설치 상태 점검은 `python -X utf8 harness_install.py --doctor` 다.

## 에이전트

정본은 `.claude/agents/` 각 파일의 frontmatter 다. model·effort 는 프로파일의
`AGENT_MODEL_POLICY` 와 대조된다(검사 29) — 한쪽만 바꾸면 막힌다.

| 이름 | 용도 | 존재 이유 |
|------|------|-----------|
| `executor` | 승인된 plan 하나를 통째로 자율 실행 | 완결된 설계서를 옮기는 일은 판단이 아니라 볼륨이다 |
| `backend` | 서버 코드 편집 | 레이어 규칙을 로드한 별도 컨텍스트 |
| `frontend` | 화면 코드 편집 | 디자인 시스템을 로드한 별도 컨텍스트 |
| `qa` | API 응답과 화면 소비의 경계면 교차검증 | 양쪽을 동시에 읽는 별도 컨텍스트가 필요하다 |
| `product-reviewer` | 사용자 관점 검수 | 역할 분리가 본질 — 만든 사람은 자기 결과를 못 본다 |
| `orchestrator` | 병렬 구현 지휘 — 소유권 배정·워커 스폰·공유 파일 직렬 적용 | 한 worktree 를 여럿이 쓰면 git 이 충돌을 못 잡는다. 소유권 판단이 유일한 방어다 |
| `impeccable-manual-edit-applier` | impeccable 수동 편집 적용 | 벤더 사본. 손대지 않는다 |

메인 루프가 몇 번의 툴 호출로 끝날 일을 위임하지 않는다. 부트스트랩 비용이 더 크다.

## 스킬

Codex의 프로젝트 조립은 [harness-assembly-cdx](../.agents/skills/harness-assembly-cdx/SKILL.md)를 사용한다.

| 이름 | 언제 |
|------|------|
| `harness-init` | 새 프로젝트를 하네스에 연결할 때. `harness_profile.py` 가 없으면 이것부터 |
| `feature-workflow` | 기능 추가·수정·버그 수정 |
| `full-feature` | 서버와 화면을 같이 만들 때 |
| `impeccable` | UI 품질 — 비평·감사·다듬기 |
| `code-audit` | 레포 전체 과설계 감사 |
| `code-debt` | `debt:` 부채 수확 |
| `code-trim` | 변경분 과설계 리뷰 |
| `md-audit` | 문서와 코드의 어긋남 감사 |
| `review-loop` | 리뷰 반복 |
| `test` | 테스트 작성 |
| `harness-retro` | 훅이 막은 기록을 읽고 규칙·게이트를 손볼지 판정 |
| `arch-diagram` | 아키텍처·흐름·시퀀스 그림을 정본 JSON 으로 쓰고 소스 증거를 박아 렌더. 구조가 바뀌는 plan 의 델타도 여기서 |

인증·토큰·결제처럼 보안이 걸린 변경은 **Claude Code 내장 `security-review`** 로 검수한다. 전용
에이전트를 만들지 않는 이유는 그 판단이 이 프로젝트 고유가 아니어서다 — 레이어 이름도 어휘도
안 쓰는 검수를 자체 구현하면 남의 도구를 이름만 바꿔 다시 만드는 것이 된다. 위 표는 이 레포가
소유한 스킬만 담는다(검사 28 이 실물과 대조하므로 내장 스킬을 행으로 넣으면 유령으로 잡힌다).
Codex 세션엔 이 내장 스킬이 없다 — 그쪽은 사람이 리뷰를 지정한다.

## 정비 — 사용자가 시켜서 도는 게 아니다

월간 감사류는 "한 달에 한 번 돌리세요"라고 적어두면 아무도 안 돈다. 사용자가 명령어를 외우고
때를 판단해야 하기 때문이다. 그 판단을 훅 ⑥ 이 대신한다.

| 정비 | 무엇을 보나 | 기본 임계치 |
|------|-------------|-------------|
| `md-audit` | 문서와 코드가 어긋난 곳 | 커밋 80개 또는 30일 |
| `code-audit` | 필요 이상으로 복잡해진 코드 | 커밋 150개 또는 60일 |
| `code-debt` | 미뤄둔 `debt:` 표시의 재고 | 표시 12개 |
| `impeccable critique` | 화면 사용성 | 화면 파일 20개 변경 또는 45일 |
| `review-loop` | 사용자 관점의 지표·문구 | 화면 파일 12개 변경 |
| `harness-retro` | 훅이 막은 기록의 패턴 | 관찰 25건 |

판정 정본은 `kernel/maintenance.py`, 임계치 조정은 프로파일의 `MAINTENANCE`, 마지막 실행
기록은 `harness_maintenance.json` 이다. 기록은 커밋한다 — 세션과 머신이 바뀌어도 공유돼야
주기가 성립한다. 화면 레이어가 선언되지 않은 프로젝트에선 화면 관련 두 항목이 아예 안 뜬다.

전부 **보고서만 내고 코드는 고치지 않는다.** 그래서 알림이 뜨면 승인 없이 실행한다.
고칠지 말지는 보고서를 본 뒤의 문제다.

## 하네스가 자라는 법

게이트는 설계된 게 아니라 사고마다 하나씩 늘었다.

사고가 나면 먼저 경위를 `dev/LESSONS.md` 에 남긴다. 무슨 일이 있었고 무엇을 잃었는지.
규칙만 적으면 다음 세션이 "이번은 예외 아닌가" 하고 넘기지만, 대가가 적혀 있으면 못 넘긴다.

그다음 기계로 검사할 수 있는지 본다. 할 수 있으면 `kernel/gates/` 에 판정을 더하고 그 절의
`> 강제:` 를 게이트 번호로 갱신한다. 못 올리면 `산문 전용 — 사유` 로 적는다. 둘 중 아무것도
안 적으면 검사 30 이 막는다. 적어놓고 판단을 미룬 상태이기 때문이다.

그래서 산문 전용으로 남은 목록이 곧 다음에 게이트로 올릴 후보다.

### 사고를 기다리지 않는 쪽 — 폐쇄 루프

위 경로는 사람이 사고를 알아채야 시작된다. 못 알아챈 마찰은 그대로 사라진다. 그래서 훅이
막을 때마다 관찰을 남기고, 그게 쌓이면 하네스가 회고할 때를 알린다.

| 단계 | 무엇이 | 어디에 |
|---|---|---|
| 관찰 | 차단·경고 훅이 막을 때마다 한 줄 | `kernel/trace.py` → `harness_trace.jsonl` |
| 채굴 | 게이트별 빈도와 반복 지점과 마찰 종류 | `kernel/retro.py` |
| 발동 | 관찰이 임계를 넘으면 정비 알림 | `kernel/maintenance.py` |
| 판정 | 규칙 위반인가 게이트 오탐인가 규칙이 틀렸나 | **사람** — `harness-retro` 스킬이 절차를 잡는다 |
| 검증 | 게이트를 고쳤으면 회귀 확인 | `tests/run_golden.py` |
| 병합 | 통과분만 반영하고 표면은 래칫 | `harness_surface.txt` |
| 부정 결과 | 거절·보류된 제안과 사유 | `dev/REJECTED.md` |

**판정만 자동화하지 않는다.** 이 하네스엔 "더 좋아졌다"를 재는 적합도 함수가 없다. 골든
대조는 회귀만 잡고 개선은 못 잰다. 적합도 없이 제안과 수용을 자동화하면 루프는 가장 싼 통과
경로로 수렴한다 — 게이트를 무르게 만들기다. `edit_surface` 래칫이 같이 들어간 이유가 이것이고,
판정이 수동인 동안에도 그 문은 닫아둬야 나중에 자동화할 여지가 생긴다.

부정 결과를 남기는 것도 같은 이유다. 거절된 제안이 기록되지 않으면 다음 회고가 같은 제안을
다시 하고, 그 반복이 결국 하나를 통과시킨다.

> 훅 command 는 `"$(git rev-parse --show-toplevel)/.claude/hooks/…"` 로 등록한다. `%CLAUDE_PROJECT_DIR%` 표기는 이 환경에서 확장되지 않고, 상대경로는 셸 툴의 잔류 cwd(`cd frontend` 한 번이면 그 뒤 전부)에 전멸한다 — toplevel 방식은 레포 안 어디서든 맞는다. 레포 밖 cwd 에서는 rev-parse 도 실패하나 상대경로도 같은 조건에서 실패하므로 순개선이다.
