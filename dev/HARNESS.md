# dev/HARNESS.md — 하네스 지도

> 담는 것: 공용 검사 계약과 런타임별 훅·스킬 연결. 담지 않는 것: 각 항목의 정본 내용(→ `.claude/` 각 파일·`kernel/` 헤더)·세션 행동 규칙(→ `CLAUDE.md`)·이 프로젝트가 무엇인지(→ `PROJECT.md`). 읽는 시점: 하네스를 파악하거나 수정할 때.

하네스를 고치려면 먼저 하네스 전체를 볼 수 있어야 하고, 이 파일이 그 지도다. 하네스 구성이 바뀌면 같은
턴에 이 파일도 갱신한다. 빠뜨리면 하네스 지도 검사(검사 28)가 실물과 대조해 잡는다.
처음 보는 사람은 [하네스 한눈에](OVERVIEW.md)에서 부품과 용어를 먼저 읽는다.
운영 계약, 게이트 상세, 팩, 정비는 `harness/` 아래 하위 문서로 나눴고 옮긴 절 자리마다 링크를 남겼다.

## 공용 하네스 운영

공용 하네스 운영(과업 명령, 플러그인 배포, 저장·종료 계약, 작업공간 판정 공유)은 [하네스 운영](harness/operations.md)으로 옮겼다.

## 구조

런타임별 훅이 공통 검사 진입점을 호출하고 커널은 프로파일을 통해 프로젝트 규칙을 읽는다.
프로젝트별 경로와 예외는 프로파일에서 정하며 실행 도구의 입력 형식은 어댑터에서 처리한다.

## Claude 훅 실행 순서

세션 시작부터 종료까지 시간순이다. **차단**은 exit 2 로 진행을 멈추고 모델에게 피드백을 준다.
**경고**는 exit 0 + `systemMessage` 로 사용자 화면에 띄우되 멈추지 않는다. 모델은 읽지 않는다 — PreToolUse 훅만
`additionalContext` 로 모델에게도 줄 수 있다. exit 1 은 훅이나 검사기가 돌지 못한 경우에만 쓴다. 화면에
"hook error" 로 보이므로 그 표시가 사실이어야 한다. 어느 쪽을 쓰는지는 아래 「단계」가 정한다.

| # | 이벤트 | 훅 | 조건 | 결과 |
|---|--------|----|------|------|
| ① | SessionStart | `code-master.md` 주입 — 코딩 페르소나(단순성 우선·근본 원인·비타협 안전) | 항상 | 통과 |
| ② | SessionStart | git·origin 검사 | 저장소 아님 또는 origin 미설정 | 경고 문자열 |
| ③ | SessionStart | 프로파일 검사 — 판정 `kernel/profile.py` `setup_notice` | `harness_profile.py` 없음, 하네스 레포 자신의 프로파일인데 원류 원격이 없음(설치 전 clone), `LANG` 미선택, 또는 `PROFILE_SCHEMA` 가 커널 요구치보다 낮음(새 항목 목록 고지) | `[HARNESS SETUP]` 경고 문자열 |
| ④ | SessionStart | 인터프리터 검사 — 훅 명령은 모두 `python` 을 먼저, 없으면 `python3` 을 찾는다(Windows 의 `python3` 는 대개 실행되지 않는 스토어 바로가기라 순서가 이렇다) | 둘 다 없음 또는 3.10 미만 | 경고 문자열 |
| ⑤ | SessionStart | `git_staleness.py` | 시작·`/clear`·compact·resume 마다 세션 sid 와 열린 과업 주입(남의 과업에는 인계 명령, worktree 없는 과업에는 그 사실) + 기본 브랜치가 origin 보다 뒤면 정렬 (**정렬만 startup 한정**) | sid 한 줄 · 과업 목록 · ff-only 자동 정렬 |
| ⑥ | SessionStart | `check_maintenance.py` | 정비 임계치 초과 (**startup 한정**) | 밀린 정비 목록 |
| ⑦ | UserPromptSubmit | `check_context_growth.py` | transcript 가 임계 초과 | 경고 + `/clear` 권고 |
| ⑧ | PreToolUse(Read) | `check_context_diet.py` | 추정 토큰이 한도를 넘는데 분할 읽기를 하지 않음 — 레포 안팎을 가리지 않는다 | **차단** |
| ⑧-1 | PreToolUse(Bash·PowerShell) | `check_bash_write.py` — 읽기 `kernel/shell.py` | 셸로 소스 파일 쓰기(리다이렉트·`tee`·`sed -i`·PowerShell 쓰기 cmdlet, 상대경로는 명령 안의 `cd` 를 따른다), 판정 명령의 exit code 를 파이프·체인으로 삼키기, 병렬 작업 중 공유 트리의 git 변경(끝난 브랜치의 `git merge --ff-only` 는 예외) | **차단** |
| ⑧-3 | 〃 | `check_bash_write.py` | 트리 밖·의존성 디렉토리를 잇는 junction·symlink 생성 | **차단** |
| ⑧-2 | PreToolUse(Edit·Write·MultiEdit·NotebookEdit·EnterWorktree·Bash·PowerShell) | `check_pretool.py` — 판정 `kernel/worktree.py`, Codex 공유 | 새 worktree 이름에 `--<sid8>` 접미 없음, 또는 `EnterWorktree(name)` 생성 | **차단** |
| ⑧-2 | 〃 | `check_pretool.py` — 판정 `kernel/worktree.py`, Codex 공유 | worktree 이름 앞부분이 내 workboard 범위와 다름 (내 보드 파일 있을 때만) | **차단** |
| ⑧-6 | 〃 | `check_pretool.py` — 판정 `kernel/isolation.py`, Codex 공유 | 남의 과업 worktree 편집 — 그 범위 보드 파일의 `#sid` 가 내 sid 가 아님 | **차단** + `kernel.task resume` 명령 |
| ⑧-6 | 〃 | 〃 | 메인 체크아웃에서 구현 파일 편집 (예외 `workboard/`·`docs/tasks/`·본체 전체에 바뀐 줄 1줄 — 이미 쌓인 커밋 안 된 줄을 더해 센다. 그래프에 컴포넌트가 없는 설정 단계에는 프로파일·`PROJECT.md`·`profiles/`·`docs/architecture/`·`.github/workflows/` 도 예외) | **차단** + `kernel.task start`·진입 명령 |
| ⑧-6 | 〃 | 〃 | 내 `#sid` 과업 파일 없이 편집 (예외 같음 — 등록 자체는 막지 않는다) | **차단** + `kernel.task start` 명령과 보드 서식 |
| ⑧-7 | 〃 | `check_pretool.py` — 판정 `kernel/exit_gate.py`, Codex 공유 | `git push`·`gh pr create`·`gh pr merge`·`git merge` 직전 나가는 트리의 체크아웃에서 `--verify` 가 exit 0 아님 (`[TOOL]`·`[DECISION]`·러너 실행 불능 포함). 한 명령줄의 합치는 명령을 전부 검사하고 `cd`·`git -C` 가 체크아웃을 정한다. 본체의 `git merge <과업 브랜치>` 는 그 브랜치의 worktree 를 검사하고, worktree 안 merge 와 `origin/…` 동기화는 대상이 아니다 | **차단** + 위반 목록 |
| ⑧-8 | 〃 | `check_pretool.py` — 판정 `kernel/irreversible.py`, Codex 와 플러그인 공유 | 되돌릴 수 없는 명령 — 기본 브랜치를 겨눈 강제 push 나 삭제 push, 메인 체크아웃의 `git reset --hard`·`git clean -f`·경로를 덮는 `git checkout -- <경로>`·작업 트리 `git restore`, 남의 `#sid` 과업이 잡은 브랜치나 worktree 의 강제 삭제, 레포 밖과 레포 루트와 공유 폴더(`.git`·`workboard`·`worktrees` 와 worktree 폴더)의 재귀 삭제. 자기 브랜치의 강제 push 와 드라이런과 worktree 안 롤백과 임시 폴더와 값 모르는 변수와 패턴 글롭은 통과하고, git 조회는 위험한 모양에서만 한다. worktree 이름 검사와 나올 때 검사보다 먼저 돈다 | **차단** + 무엇을 왜 하려 했는지 사용자에게 보고하고 사람에게 맡기라는 안내 |
| ⑧-9 | 〃 | `check_pretool.py` — 판정 `kernel/local_hooks.py`, Codex 와 플러그인 공유 | 프로파일 `LOCAL_HOOKS` 가 켠 프로젝트 훅 `harness_hooks/<이름>.py` 의 `check` 가 사유를 돌려줌. 핵심 가드가 전부 통과한 뒤에만 돈다. 훅 자체의 예외는 막지 않고 경고와 `gate_error` 관찰로 남긴다 | `MODE = "block"` 이면 **차단**, `"warn"` 이면 경고 |
| ⑧-4 | PreToolUse(Workflow) | `check_workflow_script.py` | 스크립트의 `agent(model=…)` 호출에 model 미지정 | **차단** |
| ⑧-5 | PreToolUse(Edit·Write·MultiEdit·NotebookEdit) | `check_workboard_overlap.py` | 다른 과업의 `손대는 곳` 글로브에 걸리는 파일을 편집 | 경고 (추론) — exit 0 JSON. `systemMessage` 로 사용자에게, `additionalContext` 로 모델에게 넘긴다. 후자는 문서화된 필드지만 실측 확인은 아직이다 |
| ⑨ | PostToolUse(Edit·Write·MultiEdit) | `check_file_rules.py` | 저장한 파일이 게이트 위반 | **차단** — worktree 안에서는 `[WIP]` 알림(exit 0, 모델은 `additionalContext`) |
| ⑪ | SubagentStop | `check_agent_return.py` | 반환이 임계 초과 | **차단** — 반환문이 페이로드에 없으면 통과하고 `systemMessage` 로 알린다 |
| ⑫ | Stop | `check_editing_lock.py` — 판정 `kernel/workspace.py`, Codex 공유 | `workboard/` 에 자기 `#sid` 과업 파일이 **머지 후에도** 남아 있음 (진행 중은 통과) | 경고 (추론) |
| ⑫-1 | 〃 | `check_editing_lock.py` — 판정 `kernel/workspace.py`, Codex 공유 | 주인 없는 과업 파일 — 머지됐고 브랜치가 origin·로컬 양쪽에 없음 | 경고 (추론) |
| ⑬ | Stop | `check_coding_rules.py` | 전체 게이트 검사에서 위반이 남아 있음 | **차단** — worktree 안에서는 `[WIP]` 알림(exit 0, 사용자 한 줄, 모델 몫은 다음 저장에) |
| ⑭ | Stop | `check_git_remote.py` — 판정 `kernel/workspace.py`, Codex 공유 | GitHub 원격이 설정되지 않음 | 경고 (사람 답이 필요한 조건) — 그동안 `kernel.task finish` 는 로컬에만 합친다 |
| ⑮ | Stop | `check_worktree_residue.py` — 판정 `kernel/worktree.py`, Codex 공유 | 머지 끝난 worktree 가 남아 있음 — upstream 이 자기 브랜치일 때만 push 이력으로 센다 | 경고 (추론) + 정리 순서 제시 |
| ⑯ | Stop | `check_mockup_residue.py` — 판정 `kernel/workspace.py`, Codex 공유 | `docs/mockup/` 에 판단이 끝난 시안이 남아 있음. 보드에 열린 범위의 폴더 `mockup/<범위>/` 는 검토 중이라 예외이고 `kernel.task finish` 가 archive 로 옮긴다. `wip_` 접두는 하위 호환 예외다 | **차단** |
| ⑰ | Stop | `check_task_residue.py` — 판정 `kernel/workspace.py`, Codex 공유 | 보드가 비었는데 `docs/tasks/` 루트에 산출물이 남아 있음. 리서치를 시작할 때 `kernel.task plan` 이 보드에 올리므로 승인 대기는 보드가 증명한다. `wip_` 와 최근 24시간 안에 수정한 파일(등록 전에 쓴 산출물)은 예외다 | **차단** |
| ⑱ | Stop | `check_ui_copy.py` | 브랜치에서 새로 추가된 ui 레이어 문구를 프로파일 `UI_COPY["language"]` 의 언어로 뽑아(한·일·중은 리터럴과 JSX 텍스트, 라틴 문자 언어는 JSX 텍스트만, 주석·테스트 파일 제외) Haiku(별칭 `haiku`) 호출 1회로 감수 — `ui_denylist` 명단에 없는 새 내부어·축약·구어를 잡는다. 같은 문구 집합이면 해시 캐시를 써서 다시 호출하지 않는다. 인프라 실패와 언어 미설정은 `systemMessage` 로 알리고 통과한다 | 경고 (LLM 판정) |

⚠️ **셸 게이트의 매처는 셸을 실행하는 툴을 전부 담아야 한다.** 이 환경에는 `Bash` 와 `PowerShell` 두 개가 있고, `Bash` 만 걸어두면 같은 명령이 `PowerShell` 로 그냥 나간다 — 원본 프로젝트에서 게이트 네 개가 전부 그렇게 무력화된 채 머지됐다(같은 `git switch` 가 Bash 에서는 차단되고 PowerShell 에서는 통과했다). 두 툴의 입력 필드가 똑같이 `command` 라 훅 본문은 손댈 것이 없고, 빠지는 것은 매처 한 단어뿐이라 눈에 안 띈다. 하네스 지도 검사(검사 28)는 훅 이름이 있는지만 보고 **매처 문자열은 보지 못한다**. 그래서 이 규칙은 게이트가 아니라 문서로만 지킨다. **셸 툴이 늘면 매처부터 늘린다.**

⑥ 만 `startup` matcher 로 분리돼 있고, ⑤ 는 모든 시작 이벤트에서 돌되 fetch·pull 은 `startup` 페이로드에서만 한다.
`/clear` 와 compact 마다 `git pull` 과 정비 판정이 다시 도는 것을 막으면서도 열린 과업과 세션 sid 는 다시 들어오게 하기 위해서다.

훅 명령은 전부 `python -X utf8` 로 등록한다. 빠지면 Windows cp949 에서 한글 출력이 `UnicodeEncodeError` 로 훅을 죽이고, exit 1 은 통과라 차단 훅이 조용히 꺼진다.

> 훅 command 는 `"$(git rev-parse --show-toplevel)/.claude/hooks/…"` 로 등록한다. `%CLAUDE_PROJECT_DIR%` 표기는 이 환경에서 확장되지 않고, 상대경로는 셸 툴에 남아 있는 cwd 때문에 모두 깨진다(`cd frontend` 한 번이면 그 뒤 전부). toplevel 방식은 레포 안 어디서든 맞는다. 레포 밖 cwd 에서는 rev-parse 도 실패하지만, 상대경로도 같은 조건에서 실패하므로 잃는 것 없이 나아진다.

### 단계 — 차단이냐 경고냐는 판정 근거가 정한다

훅은 네 단계를 낸다. 어느 단계를 쓸지는 심각도가 아니라 **판정 근거**가 정하고, 단계마다 채널이 다르다.
판정할 수 없는 경우와 **모델이 지금 고칠 수 없는 조건**은 통과(exit 0)다.

| 단계 | 근거 | 채널 | 해당 훅 |
|------|------|------|---------|
| **차단** | **직접 관측** — 검사기가 실제로 위반을 뱉었거나 파일이 실제로 거기 있다 | exit 2 + stderr. 모델이 읽는다 | ⑧ ⑧-1 ⑧-2 ⑧-3 ⑧-4 ⑧-6 ⑧-7 ⑧-8 ⑧-9(block) ⑨ ⑪ ⑬ ⑯ ⑰ |
| **작업 중 알림** | 링크드 worktree 안의 직접 관측. 고칠 시점이 합칠 때이므로 `[WIP]` 알림만 내고, 차단은 합치기 직전에 나올 때 검사(⑧-7)가 맡는다 | 저장은 exit 0 + `additionalContext`(모델)와 `systemMessage`(사용자). 종료는 `systemMessage` 한 줄이고 모델 몫은 다음 저장에 붙는다 | ⑨ ⑬ (worktree 안) |
| **경고** | **추론** — git 상태로 "끝났을 것"을 추측하거나, 사람이 적은 글로브로 겹침을 짚거나, LLM 이 문구를 판정한다. 또는 **사람 답이 필요한 조건** — 직접 관측이지만 모델이 지금 고칠 수 없다(원격 없음). 프로젝트 훅의 `warn` 모드는 추론 판정을 관찰 뒤에 올리기 위한 시작 단계다 | exit 0 + `systemMessage`. 사용자만 읽는다. ⑧-5 만 `additionalContext` 로 모델에게도 준다 | ⑫ ⑫-1 ⑭ ⑮ ⑱ ⑧-5 ⑧-9(warn) |
| **검사 불능** | 훅이나 검사기가 돌지 못했다 — 페이로드 파싱 실패, 시간 초과, 크래시 | exit 1 + stderr. 화면의 "hook error" 표시가 사실이다. 공유 체크아웃 ⑬ 의 크래시만 차단이다 | 전부 |

커널 게이트는 "확실한 위반만 잡는다(오탐 0)"는 원칙을 지킨다. 훅은 같은 원칙을 검출을 **끄는 대신 단계를 낮춰**
지킨다. 검출을 끄면 남은 잔해가 보이지 않으므로, 사용자에게는 매 턴 알리되 진행은 막지 않는다. 경고의 `systemMessage` 는
모델에게 닿지 않으므로, 모델이 반드시 읽어야 하는 조건이라면 경고가 아니라 차단이어야 한다. 한편
추론 판정에는 차단 권한을 주지 않는다. 경고 훅은 이 두 조건 사이에서 쓴다.
종료 시점 경고에 모델 채널을 주지 않는 이유는 Stop 의 모델 채널이 턴을 잇기 때문이다. 그것은 사실상 차단 권한이고, 모델이 추론을 따르면 §19 의 오판을 실행한다.

이렇게 정한 근거는 추론 계열 훅 두 개가 연달아 오판한 사고다(`dev/LESSONS.md` §19). ⑫ 는 진행 중인 보드 행을 막아
세션을 잠갔고, ⑮ 는 방금 만든 worktree 를 "머지 완료"로 잘못 판정해 **작업 중인 worktree 를 지우라고** 요구했다.
차단이면 잘못된 지시를 따르거나 세션이 잠기거나 둘 중 하나다.
**틀릴 수 있는 판정에는 차단 권한을 주지 않는다.**

⑱ 도 같은 계열이다. Haiku 의 문구 판정은 의견이지 관측이 아니다. 이미 알려진 조어는 UI 라벨 금칙어 검사(검사 6)가
결정론적으로 막고, 명단에 없는 새 조어는 경고로 알려 명단에 추가하도록 유도한다. 의견만으로 세션을 잠그지 않는다.

### 실패 시 방향 — 훅 오작동과 규칙 위반은 다른 사건이다

훅 오작동을 이유로 차단하면, 복구에 써야 할 툴이 바로 차단된 그 툴이라 세션이 잠긴다.

| 상황 | 방향 | 이유 |
|------|------|------|
| 훅 페이로드 파싱 실패 | 검사 불능(exit 1) | Edit·Bash 전면 차단은 훅을 고칠 수단까지 막는다 — ⑨ 를 고치려면 Edit 를 써야 하는데 그 Edit 가 다시 ⑨ 를 거친다 |
| 러너가 `VERIFY_TIMEOUT_SEC` 안에 안 끝남 | ⑨ ⑬ 모두 검사 불능(exit 1). 나올 때 검사(⑧-7)만 차단이다 — 다른 체크아웃의 커널로 위임한 검사가 시간을 넘겨도 나가는 명령이면 차단(exit 2)이다 | 검사기가 느린 것과 코드가 틀린 것은 다른 사건이다. 모델이 고칠 수 없는 조건이고, 같은 검사를 나올 때 검사가 fail-closed 로 다시 돈다. 위임이 시간을 넘겼다고 push 가 나가면 fail-closed 가 거짓이다 |
| `kernel/shell.py` 를 못 읽음 | ⑧-1·⑧-3 검사 불능(exit 1) | 읽기 모듈이 깨진 것은 규칙 위반이 아니다. 나올 때 검사와 worktree 이름 검사는 커널 안에서 같은 모듈을 쓰므로 그쪽은 커널 크래시 처리를 따른다 |
| 검사기 자체 크래시(트레이스백, `[FAIL]` 없음) | ⑨ 검사 불능(exit 1). ⑬ 은 공유 체크아웃에서 차단(exit 2), 링크드 worktree 안에서는 검사 불능(exit 1) — 모두 "규칙 위반"이 아니라 "검사 불능"으로 말한다 | 위반으로 포장하면 모델이 트레이스백을 고칠 코드로 읽고 멀쩡한 파일을 되돌린다. 고칠 대상은 커널이다. worktree 안에서 프로파일이나 커널을 고치는 중의 크래시가 매 턴 종료를 막으면 §25 가 돌아온다 |
| 규칙 위반 판정 | **차단**(exit 2) | 판정이 나온 경우다 |
| `session_id` 식별 불가 | 작업 소유권 추론만으로 차단하지 않음 | 남의 행을 삭제할 권한으로 해석하지 않는다 |
| 보드 행이 끝난 것인지 판정할 수 없음 | 통과 | 보드 오탐은 세션을 끝낼 수 없는 교착으로 이어진다 |
| 에이전트 반환문을 찾지 못함 | 통과 | 모든 에이전트를 막는 쪽이 더 위험하다(⑪ fail-open) |

작성 시점 검사(⑨)가 막지 않고 넘어가도 세션 끝에 Stop 훅 ⑬ 이 전체를 다시 검사한다. 검사가 두 겹이라
⑨ 의 검사 불능이 구멍이 되지 않는다. worktree 안에서는 나올 때 검사(⑧-7)가 세 번째 겹이고, 거기서는 시간 초과도 차단이다.

**모델이 지금 고칠 수 없는 조건은 통과시킨다.** 차단은 "고쳐라"는 신호인데 고칠 수단이 없으면
신호가 아니라 벽이다. 머지 전 보드 행이 그런 경우였다. 행을 지우면 거짓으로 완료를 보고하는 셈이라 모델에게 선택지가 없었다.
`stop_hook_active` 로 재차단만 빠져나가는 우회는 쓰지 않는다. 조건은 그대로 둔 채 알림만 끄는
것이라 다음 사람이 왜 막혔는지도 왜 안 막히는지도 못 읽는다. 훅이 도는 건 조건이 참이기
때문이고, 조건이 틀렸으면 조건을 고친다.

막을 때마다 남기는 관찰 기록, 임계 상수의 근거, 원격이 없을 때 ⑭ 의 동작은 [게이트 상세](harness/gates-detail.md)로 옮겼다.

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
| 7 | py Any | `py_any` | `Any` 타입으로 게이트를 피해 가는 것 |
| 8 | 공개 함수 타입힌트 | `type_hints` | 문서화되지 않은 모듈 경계면 |
| 9 | 시크릿 토큰 | `secrets` | 실키 하드코딩 |
| 10 | TS any | `ts_any` | 타입체커 strict 우회 — **ESLint 위임** |
| 12 | 설정 밖 환경변수 | `env_access` | 환경변수 읽는 지점이 흩어지는 것 |
| 13 | await 없는 async | `web_async` | 비동기인 척하는 동기 핸들러 |
| 15 | 전역 SSL 패치 위치 | `ssl_bypass` | 검증 우회가 아무 데서나 켜지는 것 |
| 16 | 라우트 응답 모양 | `routes_error` | 응답·에러 형식이 라우트마다 다른 것 — 라우트 함수의 `return` 은 응답 래퍼 호출·`None`·서버팩 `RESPONSE_EXEMPT` 만, 에러는 어느 응답에도 4xx 나 에러 본문을 싣지 않고 예외로. 지역 변수와 같은 파일의 도우미는 한 단계 따라간다 |
| 17 | 공용 래퍼 없는 fetch | `raw_fetch` | 캐시·에러 처리 없는 직접 호출 — **ESLint 위임** |
| 18 | 프론트 색 리터럴 | `hex_literal` | 색 하드코딩 (rgb·hsl·이름 색 포함) — 스크립트는 **ESLint 위임**, 스타일시트와 템플릿의 `<style>`·`style=` 은 텍스트 검사(`kernel/gates/ui_styles.py`). 테스트 파일은 면제 |
| 19 | 고정 폭 | `responsive` | 폰을 깨뜨리는 px 폭(문자열·숫자·Tailwind `w-[…px]`)과 `100vw` — 같은 두 갈래 |
| 20 | 브라우저 API 직접 호출 | `browser_api` | 앱 이식 때 교체 범위가 퍼지는 것 — **ESLint 위임** |
| 22 | 행동 테스트 짝 | `test_pairing` | 깨져도 아무도 모르는 수집·계산 모듈 |
| 23 | DDL 저장 타입 | `ddl_types` | 소스 정밀도를 못 담는 컬럼 |
| 24 | API 배열 옵셔널 | `api_array` | 배포 시차로 undefined 가 도착하는 것 |
| 25 | MD 작성 규칙 | `md_style` | 의미가 뭉개진 문서 |
| 26 | MD 경로 참조 | `md_path_refs` | 삭제·리네임 후 남은 유령 경로 |
| 27 | 고아 MD | `md_orphans` | 허브에서 도달 못 하는 문서 |
| 28 | 하네스 지도 | `md_harness_map` | 이 파일과 실물의 어긋남 — 양방향(빠진 실물·지도에만 남은 유령 행) |
| 29 | 에이전트 모델 정책 | `agent_model` | frontmatter 와 정책표의 드리프트 |
| 30 | 사고 절 승격 상태 | `lessons_promotion` | 사고를 적고 판단을 미루는 것. `> 강제:` 가 이름으로 인용한 `harness_gates/`·`harness_hooks/` 파일이 프로파일에 안 켜진 것(선언만 하고 연결 안 한 §15 의 구멍) |
| 31 | 소비 UI 없는 API 라우트 | `orphan_api` | 화면이 없어 사용자에겐 존재하지 않는 기능 — 라우트 인식은 서버 프레임워크팩의 정규식. 라우터 접두(`PREFIX_PATTERN`)를 붙이고, 파라미터 뒤 고정 마디(`/export`)까지 화면에 있어야 소비다. 기반 라우트(`INFRA_ROUTES`)는 보지 않는다 |
| 32 | 미정의 모듈 상수 | `undefined_const` | import 는 통과하고 호출 시점에 터지는 이름 |
| 33 | MD 함수 참조 실존 | `md_fn_refs` | 개명 후 MD 에 남은 유령 함수 |
| 34 | 선언 본문 중복 | `dup_decl` | 이름만 갈린 정본 재구현 — 지역 이름을 등장 순서로 바꾼 지문이라 변수 이름을 바꾼 복사도 잡는다. 호출 대상·멤버·리터럴은 그대로라 다른 API 를 부르면 다른 구현이다. 같은 파일 안 쌍도 센다. 함수 범위는 구문 사실이라 언어 무관이고, 분석기가 없으면 `[TOOL]` |
| 35 | 블록 중복 | `dup_block` | 함수로 안 뽑힌 복붙 — 같은 파일이면 두 창이 8줄 이상 떨어진 것만 |
| 36 | 헤더 경로 주석 | `header_path` | 파일 이사 후 남은 옛 경로 주석 |
| 37 | 함수 길이 상한 | `func_limit` | 파일 400줄 상한이 못 보는 축 — 한 파일에 400줄 함수 하나 |
| 38 | TYPE_CHECKING 짝 | `type_checking_future` | future annotations 없는 3.11 NameError — 로컬에서는 통과하고 CI 에서 깨진다 |
| 42 | 해시 네비 단일 기전 | `hash_nav` | 이벤트를 안 내는 History API 혼용 — 주소만 바뀌고 화면이 안 따라온다 — **ESLint 위임** |
| 43 | 프론트 로직 테스트 짝 | `ui_logic_tests` | tsc·빌드가 못 잡는 값 오류 — export 함수가 있는 로직 파일(화면팩 `LOGIC_EXT`). 선언이 없으면 `[N/A]` |
| 44 | 프론트 컴포넌트 테스트 짝 | `ui_component_tests` | 〃 — 렌더 테스트 없는 컴포넌트(화면팩 `COMPONENT_EXT`). 앱 진입 파일(`ENTRY_MARKERS`)은 대상이 아니다 |
| 45 | 루트 직속 잡파일 | `root_litter` | 확장자와 상관없이 루트에 쌓인 덤프·메모 — 아직 추적되지 않은 커밋 후보도 포함 |
| 46 | 프롬프트 버전 범프 | `prompt_version` | 버전은 그대로 두고 본문만 바꾼 LLM 프롬프트 — 산출물을 판정할 근거가 사라진다 |
| 47 | 프로파일 형식 | `profile_shape` | 설정 이름 오타·튜플 자리의 문자열 — 예외 없이 게이트 대부분이 대상 0건으로 조용히 초록불이 된다 |
| 48 | 이름 일관성 | `naming` | 세션마다 다른 이름 — 함수 표기(팩 `NAMING["function"]`), 같은 폴더·같은 대상의 다른 읽기 동사(`get`·`fetch`·`load` …), 응답 키 표기(`keys`), 화면 API 타입 필드 표기(`ui_keys`)와 한 타입 안 snake·camel 혼용. 탈출은 `name-ok`·`key-ok`. 팩이 `NAMING` 을 선언하지 않으면 `[N/A]` |
| 49 | 한 주인 기능 | `single_owner` | 두 번째 HTTP 클라이언트·DB 연결·날짜 포맷터 — 팩 `OWNED` 의 가족이 두 파일 이상에 나오면 파일마다 위반. 테스트는 보지 않는다. 표준 라이브러리라 의존 검사가 못 보는 재구현을 잡는다 |
| 50 | 진입 문서 공통 불변식 | `entry_invariants` | `CLAUDE.md` 와 `AGENTS.md` 중 한쪽에만 있는 공통 규칙 — 규칙 줄 끝의 `<!-- inv:<ID> -->` 표지로 대조한다(`kernel/gates/harness_self.py` `ENTRY_INVARIANTS`). 표지의 존재만 보고 문구·의미·도구 배선이 같은지는 증명하지 않는다. 진입 문서가 하나라도 없으면 `[SKIP]` |

문서↔코드 대조(`doc_sync`)는 프로파일의 `DOC_SYNC` 가 정의한 만큼 늘어난다.

언어팩이 선언한 린터는 `정적 분석(<slug>)` 섹션(`lint:<slug>`)으로 찍힌다. 도구가 없으면 `[TOOL]` 이고,
레포 전체를 보는 도구라 `--file` 모드에선 돌지 않는다. 정본은 `kernel/linters.py` 다.

로컬 게이트와 래칫, 프로젝트 전용 실행 전 규칙, 중복 검사(34·35), ESLint 위임은 [게이트 상세](harness/gates-detail.md)로 옮겼다.

## 컴포넌트 그래프와 사용자 결정

그래프 검사와 사용자 결정 기록은 [팩과 컴포넌트 그래프](harness/packs.md)로 옮겼다.

## Workflow 툴

여러 에이전트에 작업을 정해진 방식대로 나눠 돌려야 할 때(결정론적 팬아웃) 쓰는 별도 경로다. 기본은 Agent 툴로 에이전트를 띄우는 것이고, Workflow 는 루프·조건·
단계 통과를 스크립트로 고정해야 할 때만 고른다.

**계약 정본은 `.claude/agents/orchestrator.md` §4-1 이다.** 계약 네 가지 중 model 명시만 워크플로 스크립트 검사 훅(⑧-4)이 기계로
막고, 나머지 셋(격리 금지·백그라운드 금지·resume 용도 한정)은 문서로만 지킨다.

이 경로가 규약 없이 쓰이면 하네스의 모델 라우팅·격리·복구 규칙이 **하나도 적용되지 않는다.**
원본 프로젝트에서 규약 없이 한 번 돌렸을 때 그 세션의 워커 51개 중 14개가 결과 없이 죽었다(`dev/LESSONS.md` §20).

## 등급

검사 출력 등급과 exit 코드는 [게이트 상세](harness/gates-detail.md) 「등급」으로 옮겼다.

## 언어팩·프레임워크팩·아키텍처팩

팩 세 축과 구문 사실 분석기는 [팩과 컴포넌트 그래프](harness/packs.md)로 옮겼다.

## 에이전트

정본은 `.claude/agents/` 각 파일의 frontmatter 다. model·effort 는 프로파일의
`AGENT_MODEL_POLICY` 와 대조된다(에이전트 모델 정책 검사, 검사 29). 한쪽만 바꾸면 막힌다.

| 이름 | 용도 | 존재 이유 |
|------|------|-----------|
| `executor` | 승인된 plan 하나를 통째로 자율 실행 | 완결된 설계서를 옮기는 일은 판단이 아니라 볼륨이다 |
| `backend` | 서버 코드 편집 | 레이어 규칙을 로드한 별도 컨텍스트 |
| `frontend` | 화면 코드 편집 | 디자인 시스템을 로드한 별도 컨텍스트 |
| `qa` | API 응답과 그것을 쓰는 화면 사이의 경계 교차검증 | 양쪽을 동시에 읽는 별도 컨텍스트가 필요하다 |
| `product-reviewer` | 사용자 관점 검수 | 역할 분리가 본질 — 만든 사람은 자기 결과를 못 본다 |
| `orchestrator` | 병렬 구현 지휘 — 소유권 배정·워커 스폰·공유 파일 직렬 적용 | 한 worktree 를 여럿이 쓰면 git 이 충돌을 못 잡는다. 소유권 판단이 유일한 방어다 |

메인 루프가 몇 번의 툴 호출로 끝날 일을 위임하지 않는다. 부트스트랩 비용이 더 크다.

## 스킬

Codex의 프로젝트 조립은 [harness-assembly-cdx](../.agents/skills/harness-assembly-cdx/SKILL.md)를 사용한다.

| 이름 | 언제 |
|------|------|
| `harness-init` | 새 프로젝트를 하네스에 연결할 때. `harness_profile.py` 가 없으면 이것부터 |
| `feature-workflow` | 기능 추가·수정·버그 수정 |
| `full-feature` | 서버와 화면을 같이 만들 때 |
| `code-audit` | 레포 전체 과설계 감사 |
| `code-debt` | `debt:` 부채 수확 |
| `code-trim` | 변경분 과설계 리뷰 |
| `md-audit` | 문서와 코드의 어긋남 감사 |
| `review-loop` | 리뷰 반복 |
| `test` | 테스트 작성 |
| `harness-retro` | 훅이 막은 기록을 읽고 규칙·게이트를 손볼지 판정 |

인증·토큰·결제처럼 보안이 걸린 변경은 **Claude Code 내장 `security-review`** 로 검수한다. 전용
에이전트를 만들지 않는 이유는 그 판단이 이 프로젝트 고유가 아니어서다 — 레이어 이름도 어휘도
안 쓰는 검수를 자체 구현하면 남의 도구를 이름만 바꿔 다시 만드는 것이 된다. 위 표는 이 레포가
소유한 스킬만 담는다(검사 28 이 실물과 대조하므로 내장 스킬을 행으로 넣으면 유령으로 잡힌다).
Codex 세션엔 이 내장 스킬이 없다 — 그쪽은 사람이 리뷰를 지정한다.

## 정비와 수명

정비 주기, CI, 개발 레포와 배포 레포, 하네스가 자라는 법은 [정비와 하네스 수명](harness/lifecycle.md)으로 옮겼다.
