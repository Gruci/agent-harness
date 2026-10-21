# dev/CONVENTIONS.md — 결정된 관례 레지스트리

> 담는 것: 갈림길에서 이미 결정된 관례와 공용 헬퍼 레지스트리. 담지 않는 것: 레이어 구조(→ `dev/ARCHITECTURE.md`)·이름 규칙(→ `dev/NAMING.md`)·규칙의 배경(→ `dev/LESSONS.md`). 읽는 시점: 새 파일이나 함수를 쓰기 전. 재구현 전에 헬퍼 표를 먼저 본다.

> **목적: 서로 다른 에이전트와 세션에서도 같은 코드 관례를 유지한다.**
> 운영 규칙 2줄:
> 1. **관례가 갈리는 선택을 새로 하게 되면 이 표에 등재하고, 검사 가능하면 `kernel/gates/`(이 레포 전용은 `harness_gates/`)에 검사를 추가한다.**
> 2. **이 표와 코드가 충돌하면 표가 정본이다** (표를 바꾸려면 사용자 합의 후).
> 이 문서는 산문 없이 표로만 쓴다. 새 파일을 쓰기 전에 이 표와 레이어 MD의 정본 예시 파일(golden exemplar)을 읽는다.

## 공통 설계

| 주제 | 정본 | 적용 |
|---|---|---|
| 분류와 허용 의존 | [컴포넌트 승인](COMPONENTS.md) | 첫 코드부터 적용한다 |
| 정책과 기술 분리 | [아키텍처](ARCHITECTURE.md) | 선택한 언어의 모듈 표현을 사용한다 |
| 저장소 접근 | 승인된 포트와 어댑터 | 읽기와 쓰기 폴더 이름을 일괄 강제하지 않는다 |
| 커넥션 수명 | I/O에 필요한 범위로 제한 | 업무 계산을 하느라 커넥션을 쥐고 있는 시간을 늘리지 않는다 |
| 환경변수 | 프로젝트가 정한 설정 경계 | 정책에서 직접 읽지 않는다 |
| 공용 기능의 주인 | HTTP 클라이언트·DB 연결·날짜 포맷처럼 여러 곳이 쓰는 기능은 모듈 하나가 맡고 나머지는 그 모듈을 부른다 | 가족은 언어팩·화면팩 `OWNED`, 한 주인 검사(`single_owner`)가 잡는다. 둘이 꼭 필요하면 사람이 그 파일을 동결 목록(`harness_baseline.txt`)에 올린다 — 이 검사에는 예외 목록(`ALLOWLIST`) 키가 없다 |
| 모듈 진입점 | import만으로 외부 작업을 시작하지 않는다 | 언어별 진입 방식을 따른다 |
| 숫자 정제 | 0은 유효값이다 | NULL로 바꾸지 않는다 |
| 시각 | 시간대를 명시한다 | 업무 기준 시간대는 프로젝트가 정한다 |
| 수집 복구 | 누락 재시도와 중복 처리를 설계한다 | 수집 유스케이스가 있을 때 적용한다 |

## 화면 관례 (스택 무관)

> 화면 레이어는 프로파일 `CHECK_PATHS["ui"]` 다. 훅 이름·컴포넌트 디렉토리·라우터처럼 스택마다 다른 것은 이 표가 아니라 「스택 관례」 절에 있다. 번호는 참조 키라 다시 매기지 않는다 — 스택 조각으로 옮긴 F3·F8 은 비어 있다.

| # | 주제 | 정본 | 근거·예외 |
|---|------|------|-----------|
| F1 | 데이터 호출 | 프로파일 `ALLOWLIST["ui_fetch_wrappers"]` 에 등록한 공용 래퍼 하나만 거친다. raw fetch 금지 | 검사 17. 첫 구현 시 래퍼부터 만든다 |
| F2 | 색상 | hex·rgb()·이름 색 리터럴 금지. 토큰 파일(`CHECK_PATHS["ui_tokens"]`)의 상수나 CSS var를 쓴다. **예외: 토큰 파일 자신과 CSS 변수 정의 줄(`--x: …`)** | 게이트 — 스크립트는 ESLint, 스타일시트·템플릿은 텍스트 검사 |
| F4 | 차트 래퍼 | 차트는 래퍼 모듈을 거친다(기본 옵션이 자동으로 들어간다). 차트 라이브러리로 차트를 직접 만들지 않는다 | 래퍼 위치는 스택 관례 |
| F5 | 사용자 노출 텍스트 | 프로파일 `UI_COPY["language"]` 의 언어로 쓴다. 값이 없을 때와 로딩 중의 표기는 그 언어로 한 벌만 정해 공용 상수로 둔다. 이모지 금지(문서화된 예외만 허용) | 문구 감수 훅(⑱)이 같은 키를 읽는다 |
| F6 | 컴포넌트 배치 | 한 페이지 전용과 두 페이지 이상이 쓰는 공용을 디렉토리로 가른다 | 디렉토리 이름은 스택 관례. 공용화 시점은 `design/COMPONENTS.md` |
| F7 | 수치 표시 | 표시 변환은 공용 포맷 모듈로 한다. 페이지 안에서 fmt 함수를 다시 만들지 않는다 | 첫 구현 때 만들고 공용 헬퍼 표에 등재. 로케일 포맷이 두 파일에 생기면 한 주인 검사가 잡는다 |
| F9 | 브라우저 전용 API | `window.`·`document.`·`localStorage` 는 플랫폼 래퍼를 거친다. 래퍼는 프로파일 `ALLOWLIST["ui_platform"]` 에 등록하고, 불가피하면 `// web-ok: 사유` | 검사 20. 앱으로 이식할 때 래퍼 파일 하나만 바꾸면 끝난다 |

## 데이터셋 표시 규약

> 같은 데이터셋이 화면마다 다른 순서나 라벨로 나오면 사용자는 서로 다른 데이터로 읽는다. 기존
> 데이터셋을 새 표·차트·카드에 얹기 전에 이 표를 보고, 없는 축이면 소비처를 grep 해
> 현행 관례를 확인한 뒤 **행으로 등재하고 따른다.** 순서·라벨은 화면이 정하지 않는다.

| 데이터셋(축) | 순서 정본 | 라벨 정본 |
|---|---|---|
| (첫 데이터셋 축 확정 시 등재) | | |

## 과잉설계 방지

| # | 규칙 | 위반 예시 | 올바른 대안 |
|---|------|----------|------------|
| P1 | 한 곳에서만 쓰는 추상화 금지 | 1회용 제네릭 래퍼 클래스 | 인라인 또는 함수 1개 |
| P2 | stdlib로 되면 외부 dep 추가 금지 | `arrow` for 단순 날짜 | `datetime` |
| P3 | 사용하지 않는 "유연성" 파라미터 금지 | `strategy=`, `mode=` (호출부 1개) | 필요해지면 그때 추가 |
| P4 | 미래 요구사항에 대한 투기적 설계 금지 | "나중에 멀티테넌트 되면…" 분기 | 현재 요구사항만 구현 |
| P5 | 이미 있는 헬퍼 재구현 금지 | 아래 헬퍼 표·CONVENTIONS 무시하고 새로 만듦 | 기존 것 재사용 |

> 검토와 부채 수확은 [공통 작업 절차](workflows/README.md)를 따른다.
>
> 의도적 단순화(알려진 상한이 있는 지름길)는 `# debt: <상한>, <업그레이드 조건>` 주석으로 표시한다. `/code-debt`가 이 마커를 모아 부채 원장을 만든다.

## 스택 관례

> 프로파일 `FRAMEWORK` 가 고른 팩의 조각을 초기 설정의 스택 맞춤이 아래 표식 사이에 넣는다. 조각의 정본은 `kernel/frameworks/<이름>.md` 이고, 같은 이름의 `profiles/framework/<이름>.md` 가 있으면 프로젝트 것이 이긴다. 기본 탑재 조각은 `kernel/frameworks/react.md` 와 `kernel/frameworks/fastapi.md` 다.
> 표식 사이는 손으로 고치지 않는다. 고칠 것은 조각이고, `python -X utf8 -m kernel.conventions` 가 절을 다시 생성한다.

<!-- harness:stack-conventions begin (kernel/frameworks/*.md 에서 생성 — 손으로 고치지 않는다) -->
(선택한 프레임워크팩 없음 — 초기 설정의 스택 맞춤이 채운다)
<!-- harness:stack-conventions end -->

## 공용 헬퍼 레지스트리 (동일 목적 재구현 금지 — 신설 전 이 표 확인)

> 공용 헬퍼를 만들거나, 두 곳 이상에서 반복되는 코드를 공용으로 올릴 때 여기 등재한다.

| 모듈 | 제공 | 소비 도메인 |
|------|------|------------|
| `kernel/hook.py` | 런타임별 입력 정규화, 저장 시점과 종료 시점 검사를 `Verdict` 하나로 접기, 다른 체크아웃으로 위임 | 양쪽 훅은 검사 실행을 재구현하지 않는다 |
| `kernel/codex_hook.py` | Codex 전용 분기 — 저장 후 보드 겹침 경고와 작업공간 Stop 판정 모음 | Claude 판정을 바꾸지 않는다. `kernel/hook.py` 가 `--agent codex` 일 때만 부른다 |
| `kernel/channel.py` | 판정을 런타임 채널(exit 코드·stderr·`additionalContext`·`systemMessage`)로 옮기기, worktree 종료 알림의 보관과 다음 저장 전달, Codex 작업공간 판정 접기 | 훅은 exit 코드와 JSON 필드를 직접 고르지 않는다. 누가 무엇을 읽는지의 정본이다 |
| `kernel/pretool.py` | PreToolUse 처리. 판정 결과를 (exit, `systemMessage`)로 옮긴다 | Claude 래퍼 `check_pretool.py` 와 Codex 진입점이 같이 쓴다 |
| `kernel/shell.py` | 셸 명령줄을 단순 명령·실행 위치·쓰기 대상·git 하위 명령으로 읽기 (`commands`·`git_args`·`write_targets`·`native`·`join`) | 셸 명령을 판정하는 검사는 토큰을 직접 쪼개지 않는다. 표준 라이브러리만 쓰므로 훅 폴더도 쓴다. 판정은 각 소비자가 한다 |
| `kernel/isolation.py` | 편집 전 격리 가드(worktree 주인 — 1줄 예외보다 먼저·메인 체크아웃·보드 등록·본체 전체에 한 번인 1줄 예외)와 생성 파일 목록 `GENERATED` | 〃. 격리 예외 경로 목록과 안내문의 정본이다 |
| `kernel/exit_gate.py` | 합치는 명령 읽기(`exit_commands`), 나가는 트리 고르기(`outgoing_checkout`), 한 체크아웃의 `--verify` 실행(`verify_checkout`), 러너 출력에서 판정 줄만 거르는 `verdict_lines` | 나올 때 검사와 `task finish` 가 같이 쓴다. 합치기 명령 목록과 판정 줄 거르기의 정본이다 |
| `kernel/irreversible.py` | 되돌릴 수 없는 셸 명령 판정(`guard`) — 기본 브랜치 강제·삭제 push, 메인 체크아웃의 `reset --hard`·`clean -f`, 남의 과업 브랜치·worktree 강제 삭제, 레포 밖·공유 폴더 재귀 삭제 | `kernel/pretool.py` 가 셸 명령마다 worktree 이름·나올 때 검사보다 먼저 부른다. 플러그인 코어에서도 돈다. 차단 사유와 안내문의 정본이다 |
| `kernel/workboard.py` | 보드 위치(`board_dir`)와 서식 읽기·쓰기(`field`·`list_field`·`sid_of`·`board_text`·`add_list_item`), 겹침 판정 | 훅과 과업 명령은 보드 파일을 직접 파싱하지 않는다 |
| `kernel/task_status.py` | 공유 보드와 실제 Git 작업 사본 및 최근 로컬 반영을 읽는 세션 요약 | 상태 명령과 세션 시작 알림은 완료 체크박스를 다시 해석하지 않는다 |
| `kernel/preflight.py` | 환경 진단과 이미 선택한 스택의 완료 설정 보완 | 기본 설정을 중복 선언하지 않고 기존 테스트 명령과 필수 목록을 보존한다 |
| `kernel/task.py`·`kernel/task_finish.py` | 과업 시작·인계·끝내기 명령과 공용 git 호출(`git`·`fail`) | 과업의 기계 단계를 산문으로 다시 적지 않는다. 절차 문서는 이 명령을 가리킨다 |
| `kernel/finish_checks.py` | finish 의 합치기 전 판정 — 범위 대조(`check_touch`), 제품 테스트와 후보 고정(`product_tests`), 커밋 안 된 변경(`uncommitted`), 소규모 실측과 조기 알림(`small_counts`·`small_warning`), 공유 프로파일 값 읽기(`shared_setting`) | git 경로는 `-z` 로 읽는다. `task_finish` 를 import 하지 않는다 |
| `kernel/tests_run.py` | 제품 테스트 실행과 JUnit 건수 판정, `TESTS` 선언 형식의 정본(`declaration_errors`) | finish·CI·프로파일 형식 검사가 같이 쓴다. `kernel.profile` 을 import 하지 않는다 |
| `kernel/required.py` | 졸업 판정(`graduated`)과 필수 검사 섹션 | 러너와 문서 게이트가 같은 졸업 규칙을 쓴다 |
| `kernel/task_lock.py` | 공유 Git 디렉터리의 프로세스 잠금 | 과업과 관찰 기록은 잠금을 재구현하지 않는다 |
| `kernel/team_resources.py` | 변경 자원 정규화와 겹침 및 diff 권한 판정 | 조정기와 로컬 편집 가드 및 CI가 같은 판정을 쓴다 |
| `kernel/team_store.py` | 원자적 과업 선점과 임대 및 세대 검증 | HTTP 처리기는 상태 전이를 재구현하지 않는다 |
| `kernel/team_client.py` | 저장소에 바인딩된 인증 HTTP 요청 | 과업 명령과 CI는 토큰을 직접 직렬화하지 않는다 |
| `kernel/team_tasks.py` | 로컬 영수증과 멱등 요청 및 임대 갱신 | 팀 과업의 로컬 실행 상태를 한 곳에서 관리한다 |
| `kernel/team_git.py` | 실제 Git 후보와 제출 커밋 대조 및 원격 머지 확인 | 작업자 보고를 통합 증거로 사용하지 않는다 |
| `kernel/team_admission.py`·`kernel/team_ci.py` | 신뢰된 검사기 격리와 workflow 실행 증거 연결 | 후보 코드를 통합 인증정보로 실행하지 않는다 |
| `kernel/team_withdraw.py` | 원격 PR 종료 확인 후 후보 철회 | 조정기 세대 변경 전에 대기 중인 PR을 차단한다 |
| `kernel/trace.py` | 관찰 기록 — 공유 `.git` 의 대기 파일에 쓰기, 논리 사건으로 합쳐 읽기(`records`·`merged`), `flush`·`reclaim` | 훅은 추적 파일을 직접 열지 않는다. 반복 수를 직접 세지 않는다 |
| `.claude/hooks/_hookio.py` | 훅 페이로드 읽기, 관찰 기록 위임, 차단(`emit`)·경고(`warn`)·안내(`notify`) 출력 | Claude 전용 훅 래퍼. exit 코드와 `systemMessage` 를 직접 찍지 않는다 |
| `kernel/worktree.py` | worktree 이름·자리·범위 판정과 머지 끝난 worktree 판정 | Claude 래퍼와 Codex 진입점이 같은 판정을 쓴다. 문구도 여기가 정본이다 |
| `kernel/workspace.py` | `Finding` 과 종료 시점 작업공간 판정(보드·git 원격·목업·과업 산출물) | 〃. 새 Stop 판정은 `Finding` 을 돌려주고, 출력 채널은 어댑터가 맡는다 |
| `kernel/harness_setup.py` | 공용 하네스의 파일·스킬·훅 연결 진단 | 설치와 업그레이드 후 같은 진단을 사용한다 |
| `kernel/codex_permissions.py` | Codex 전역 자율 실행 설정과 지침 병합 | 초기화 진입점에서 재사용하며 관련 없는 설정을 보존한다 |
| `kernel/facts.py` | 파일 하나의 구문 사실(함수·import·최상위 이름)과 언어별 분석기 선택 | 게이트와 `pack_check` 는 `ast` 나 tree-sitter 를 직접 열지 않는다 |
| `kernel/conventions.py` | 프레임워크팩 조각 합성과 「스택 관례」 절 재생성 | 초기 설정의 스택 맞춤이 부른다. 절을 손으로 고치거나 조각을 다른 문서에 복사하지 않는다 |
| `kernel/shipped.py` | clone 이 싣고 온 하네스 레포 상태 정리 — 관찰·정비 기록 비우기, 첫 커밋 그대로인 원류 전용 파일 삭제 | 설치가 하네스 자신의 프로파일을 교체할 때 한 번 부른다 |
| `kernel/upgrade.py` | 원류 이력으로 하네스 소유 파일마다 판정하는 업그레이드와 버전 확인 | 설치 스크립트의 `--check-update`·`--upgrade` 가 위임한다. 로컬 수정이 있으면 멈춘다 |
| `kernel/profile.py` | 원류의 이전 이름을 포함한 GitHub 주소 비교(`repo_key`) | 설치와 프로파일은 저장소 주소 비교를 다시 구현하지 않는다 |
| `kernel/sections.py` | 러너의 등급 판정 헬퍼(`entry`·`syntax_section`·`ui_entry`)와 조건부 `[SKIP]` 사유 표 | 러너와 테스트가 같은 판정을 쓴다. 새 게이트의 등급 분기는 여기 헬퍼로 만든다 |
