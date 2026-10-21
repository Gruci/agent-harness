# dev/harness/operations.md — 공용 하네스 운영

> 담는 것: Claude 와 Codex 가 같이 쓰는 운영 계약 — 과업 명령, 플러그인 배포, 전역 자율 실행, 저장·종료 알림 채널, 작업공간 판정 공유. 담지 않는 것: 훅 순서와 게이트 표(→ [하네스 지도](../HARNESS.md))·여러 PC 의 팀 실행(→ [팀 실행](../TEAM.md)). 읽는 시점: 런타임 연결이나 과업 명령, 알림 채널을 고치거나 확인할 때.

여러 PC의 과업 선점과 원격 통합 계약은 [팀 실행](../TEAM.md)이 정본이다.

공통 절차는 [작업 절차 허브](../workflows/README.md)가 정본이다.
각 에이전트의 진입 문서와 스킬은 공통 절차에 자기 도구만 연결한다.

| 책임 | 계약 |
|---|---|
| 검사 판정 | `kernel/runner.py`가 양쪽에 같은 결과를 낸다 |
| 저장·종료 실행 | `kernel/hook.py`가 입력과 오류 등급을 공통 처리한다 |
| Claude 연결 | 저장·종료 Python 훅과 PreToolUse 래퍼(`check_pretool.py`)가 공통 진입점을 호출한다 |
| Codex 연결 | `.codex/hooks.json`이 Bash·apply_patch·Edit·Write 실행 전과 patch 후와 Stop에 공통 진입점을 호출한다. 과업 명령 `kernel.task` 도 두 런타임 공용이다 |
| 설치 진단 | `python -X utf8 harness_install.py --check-agents`로 누락과 배선 불일치를 검사한다 |

## 과업 명령

괄호 안 기호(E·F·G·H)는 그 명령이 닫은 결함 이름이고, 경위는 `kernel/task.py`·`kernel/task_finish.py` 헤더에 있다.

판단 단계(범위 인터뷰·research·plan·승인)는 그대로다. 모델이 손으로 밟던 기계 단계만 `python -X utf8 -m kernel.task` 로 접었다.
정본은 `kernel/task.py`(start·resume·명령줄)와 `kernel/task_finish.py`(finish 상태 기계)이고, 절차는 `workboard/README.md` 다.

| 명령 | 닫는 결함 |
|---|---|
| `status` | 현재 계획과 작업 사본 및 최근 로컬 반영을 한 번에 찾지 못하던 것 |
| `plan` | 보드 등록이 3단계였는데 산출물은 1단계에 생겨, 계획 중인 범위가 다른 세션에 안 보이고 승인 대기 동안 남은 산출물 검사(⑰)가 턴을 막던 것 |
| `start` | 손으로 지은 worktree 이름을 훅이 사후에 막던 것. `origin/<기본>` 에서 딴 브랜치에 upstream 이 자동 등록돼 합친 뒤 `branch -d` 가 거부되던 것. 요약 없는 14칸 plan 이 그대로 승인 요청이 되던 것. `--small` — 작은 수정에도 research·plan 을 쓰던 것(크기는 finish 가 잰다) |
| `finish` | 합치기 검사가 합치기 전 본체를 보던 것(E). 훅이 더럽힌 추적 파일 때문에 ff 가 거부되던 것(F). 커밋된 적 없는 plan 을 `git mv` 할 수 없던 것(G). 저장 훅이 지도를 갱신했다고 가정하던 것. 래칫 파일 증가가 어디에도 안 남던 것. 원격이 없으면 첫날 설정조차 끝낼 수 없던 것(로컬에만 합친다). 커밋 없던 과업을 "merged" 라고 보고하던 것. 소규모 과업이 상한을 넘은 채 합쳐지던 것 |
| `resume` | 새 session_id 로는 자기 과업도 못 고치던 것(H). `/clear` 뒤 열린 과업이 다시 안 들어오던 것 |
| `abandon` | 버린 과업을 손으로 치우다(`worktree remove --force`·`branch -D`) 남의 과업이나 커밋 안 한 작업까지 지우던 위험 |

finish 는 나올 때 검사(⑧-7)가 지키는 셸 명령이 아니다 — 같은 `verify_checkout` 을 직접 부른다. 손으로 합치는 길은 ⑧-7 이 지킨다.

세션 재개 상태의 정본은 `kernel/task_status.py`다.
`python -X utf8 -m kernel.task status --sid <sid8>`는 소유권 변경 없이 공유 보드와 실제 작업 사본 및 결정 대기를 읽는다.
현재 계획과 그 승인 근거를 먼저 읽으며 보관된 체크박스를 열린 작업의 증거로 쓰지 않는다.
최근 아카이브의 로컬 반영만으로 원격 push나 테스트 통과를 주장하지 않는다.
Git 조회가 실패하면 완료 여부를 모른다고 표시한다.

## 플러그인 배포

같은 커널이 Claude Code 플러그인으로도 깔린다. 레포 루트가 곧 플러그인이고 매니페스트는 `.claude-plugin/` 에 있다.

| 항목 | 계약 |
|---|---|
| 싣는 것 | 저장(⑨)·종료(⑬)·셸 쓰기(⑧-1·⑧-3)·나올 때 검사(⑧-7)·되돌릴 수 없는 명령 가드(⑧-8)와 `harness-init` 스킬. 작업 절차 훅과 나머지 스킬은 싣지 않는다 |
| 도는 곳 | `harness_profile.py` 가 있고 템플릿 커널(`kernel/hook.py`)이 없는 체크아웃. 다른 레포에서는 훅이 exit 0 으로 비킨다 |
| 루트 | 플러그인 진입점이 `HARNESS_ROOT` 로 프로젝트를 커널에 알린다. 정본은 `kernel/context.py` 다 |
| 명령 | `python -X utf8 "<플러그인>/kernel" <하위 명령>`. 정본은 `kernel/__main__.py` 헤더이고 경로는 세션 시작 알림이 준다 |
| 업데이트 | `/plugin update dev-harness@dev-harness`. `--upgrade` 는 템플릿 전용이다 |

Codex에서는 프로젝트와 새 훅 정의를 런타임에서 신뢰해야 실행된다.
공식 CLI의 `/hooks`에서 확인하며 호스트 앱은 해당 앱의 훅 지원과 신뢰 설정을 확인한다.
파일 진단 통과는 실제 훅 활성화의 증거가 아니다.
근거는 [공식 Codex 훅 문서](https://learn.chatgpt.com/docs/hooks)다.

### 플러그인 이름 변경

이전 agent-harness 플러그인을 설치했다면 Claude Code 세션에서 아래 순서로 새 이름으로 옮긴다.
이전 마켓플레이스를 제거하면 그곳에서 설치한 플러그인과 연결 설정도 제거된다.

```text
/plugin marketplace remove agent-harness
/plugin marketplace add Gruci/dev-harness
/plugin install dev-harness@dev-harness
```

프로젝트의 하네스 프로파일과 검사 기록은 유지한다.
명령의 설치와 제거 동작은 [공식 플러그인 관리 문서](https://code.claude.com/docs/en/discover-plugins)가 정본이다.

## 전역 자율 실행 초기화

`python -X utf8 setup_global_permissions.py --agent codex`가 Codex 전역 자율 실행을 설치한다.
`--agent both`는 Claude와 Codex를 모두 초기화한다. 인자 없이 실행하면 기존처럼 Claude를 초기화한다.
Codex 경로는 `CODEX_HOME`을 우선하고 없으면 사용자 홈의 `.codex`를 사용한다.
도구 승인 정책은 `never`이며 샌드박스는 전체 접근을 사용한다.
새 권한 프로파일 형식이 이미 있으면 같은 의미의 전체 접근 프로파일을 사용한다.
전역 지침은 중요한 모호함의 확정과 구현 전 계획 승인에서만 질문하도록 정한다.
이미 받은 승인은 다시 요구하지 않는다.
설치 전 기존 파일을 백업하고 모델·인증·플러그인 설정을 보존한다.
`python -X utf8 setup_global_permissions.py --agent codex --check`는 쓰기 없이 설치 상태를 확인한다.
현재 세션에 고정된 제한이나 호스트가 강제한 설정은 사용자 전역 파일보다 우선한다.
설치 완료와 호스트 적용 완료를 구분하며 새 세션에서 확인한다.

## 저장·종료 계약

저장 훅은 이미 발생한 편집을 취소하지 않고 수정 피드백을 반환한다.
Codex patch의 모든 추가·수정·이동 대상은 payload의 작업 디렉터리 기준으로 검사한다.
저장과 종료 검사는 선택한 SOURCE_EXT와 UI_EXT를 같은 기준으로 수집한다.
종료 시에는 git 추적 파일과 아직 추가하지 않은 소스를 함께 검사한다.
사용자 결정 대기는 완료가 아니며 Stop은 질문 후 정상적으로 턴을 끝낼 수 있다.
다른 worktree를 검사할 때는 그 체크아웃의 프로파일과 커널을 사용한다.
링크드 worktree 안에서는 저장·종료 검사가 판정만 하고 막지 않는다. 대신 합칠 때 막힐 항목을 `[WIP]` 머리말을 붙여 알린다.
실제 차단은 나올 때 검사(⑧-7)가 맡는다. 나올 때 검사는 worktree 작업을 본체로 합치는 push·PR·merge 직전에 도는 검사다.

알림 채널의 정본은 `kernel/channel.py` 다. 모델이 읽는 본문은 판정 줄과 결정 알림뿐이다 — 저장은 `[FAIL]`·`[DECISION]` 머리와 그 아래 항목, 종료는 `[TOOL]` 까지.

| 알림 | Claude | Codex |
|---|---|---|
| worktree 저장 | exit 0 + JSON. `additionalContext` 는 모델에게, `systemMessage` 한 줄은 사용자에게 | exit 0 + `systemMessage` |
| worktree 종료 | exit 0 + `systemMessage` 한 줄. 모델 몫은 그 체크아웃의 git 디렉터리에 보관했다가 같은 세션의 다음 본 대화 저장이 `[TURN END]` 머리로 한 번만 받는다. 서브에이전트의 저장은 보관본을 가져가지 않는다 | exit 0 + `systemMessage` |
| 결정 알림만 | 저장은 `additionalContext`. 종료는 `systemMessage` 와 보관 | `systemMessage` |

종료 시점에 모델 채널을 쓰지 않는 이유는 그 채널이 턴을 잇기 때문이다(`dev/LESSONS.md` §26). 다음 저장은 모델이 코드를 고치는 순간이고, 저장 없이 끝내면 나올 때 검사가 같은 목록으로 막는다.

검사를 공용화했다고 해서 모든 도구 정책을 똑같이 강제한다는 뜻은 아니다.
셸로 편집해 저장 시점 검사를 거치지 않은 경로도 종료 시 전체 검사는 통과해야 한다.

## 작업공간 판정 공유 — worktree 이름·격리 가드·나올 때 검사와 종료 시점 잔존 검사

worktree 이름·위치 검사(⑧-2), 격리 가드(⑧-6), 나올 때 검사(⑧-7), 되돌릴 수 없는 명령 가드(⑧-8), 종료 시점의 작업공간 검사(⑫~⑰)는 Claude와 Codex가 같은 판정 코드를 쓴다.
판정 코드의 정본은 다섯 파일이고, 셸 명령줄 읽기는 `kernel/shell.py` 하나다.

- `kernel/worktree.py`: 이름, 위치, 범위, 머지가 끝난 worktree, git 이 모르는 `worktrees/` 폴더
- `kernel/isolation.py`: worktree 주인(1줄 예외보다 먼저), 메인 체크아웃, 보드 등록, 본체 전체에 한 번인 1줄 예외
- `kernel/exit_gate.py`: 합치는 명령 읽기와 나가는 트리 고르기, `--verify` 실행
- `kernel/irreversible.py`: 기본 브랜치 덮어쓰기, 공유 체크아웃 비우기, 남의 작업 강제 삭제, 레포 밖·공유 폴더 재귀 삭제. 플러그인 코어에서도 돈다 — 나중에 게이트가 다시 잡아 줄 수 없는 손실이라 런타임별로 두지 않는다
- `kernel/workspace.py`: 보드, git 원격, 목업, 과업 산출물
- `kernel/shell.py`: 명령줄을 단순 명령·실행 위치·쓰기 대상으로 읽는다. 표준 라이브러리만 써서 Claude 셸 쓰기 훅(⑧-1·⑧-3)도 같은 읽기를 쓴다. 명령은 단순 명령의 머리에서만 찾고, heredoc·감싼 셸·git 전역 옵션·`cd` 를 걷어 낸다

Claude 훅은 페이로드 처리, stderr 출력, trace 기록, exit 코드만 맡는 래퍼이고, Codex 는 `kernel/hook.py` 가 PreToolUse(Bash·apply_patch·Edit·Write)와 Stop 에서 같은 판정을 부른다. PreToolUse 분기는 `kernel/pretool.py` 다.
차단할지 경고할지는 판정 코드가 정하고, 그 결과를 알리는 채널만 런타임마다 다르다.

| 런타임 | 차단 | 경고 |
|---|---|---|
| Claude | exit 2 + stderr | exit 0 + `{"systemMessage": …}` — 사용자 화면에만. PreToolUse 의 ⑧-5 만 `additionalContext` 로 모델에게도 준다 |
| Codex | exit 2 + stderr | exit 0 + `{"systemMessage": …}` 하나다 — 결정 알림과 저장 후 보드 겹침도 같은 채널이다. 차단이 섞인 턴에는 stderr 에 덧붙인다 |

worktree 안 알림의 채널은 「저장·종료 계약」에 있다. 두 런타임 모두 exit 1 은 검사 불능에만 쓴다.

Codex 에는 EnterWorktree 툴이 없어 `git worktree add` 만 대상이다. Codex 편집 가드는 apply_patch 의 대상 경로와 `+`·`-` 줄 수로 판정한다.
도구 사용 전 권한과 나머지 Claude 전용 보조 훅(SessionStart·큰 파일 Read 제한·셸 쓰기·워크플로·UI 카피)은 런타임별로 유지한다.
