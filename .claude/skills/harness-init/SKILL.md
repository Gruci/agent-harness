---
name: harness-init
description: >
  Onboarding interview that connects this harness to a project. Asks what the
  user is building in plain language, explains the real constraints of each
  stack candidate so the user can choose, writes the profile, runs the install,
  and confirms no gate is silently skipped.
  Use when the user says "새 프로젝트 시작", "하네스 깔아줘", "뭐부터 해야 돼",
  "harness-init", "/harness-init", "set up the harness", "start a new project",
  or when a session begins with a [HARNESS SETUP] notice (no harness_profile.py,
  the harness repo's own profile left in a clone, or LANG not chosen yet).
---

# harness-init

> 담는 것: 프로젝트를 하네스에 연결하는 온보딩 인터뷰 절차. 담지 않는 것: 게이트 각각의 판정 근거(→ `dev/HARNESS.md`)·앱 코드 작성(→ 기능 작업 스킬). 읽는 시점: 새 프로젝트를 시작하거나 `harness_profile.py` 가 없을 때.

**상대가 스택을 모른다고 가정한다.** "A 쓸래 B 쓸래"처럼 기술 이름만 던지는 질문은 답을 아는 사람만 답할 수
있는 질문이고, 그걸 물으면 온보딩이 아니라 시험이다. 만들려는 것을 묻고, 언어와 프레임워크가
미정이면 **후보의 실제 제약을 설명하고 사용자가 고른다.** 절차 정본은
`dev/workflows/harness-assembly.md` 이고 이 스킬은 그 절차에 도구 호출을 연결한다.

커널은 `harness_profile.py` 하나로만 프로젝트를 안다. 이 절차의 실질은 그 파일을 실물에 맞게
채우는 것이고, 끝났을 때의 목표는 게이트를 켜는 게 아니라 **꺼진 게이트를 없애는 것**이다.

## 플러그인으로 설치한 경우

`/plugin install agent-harness@agent-harness` 로 깔았으면 커널은 프로젝트가 아니라 플러그인 폴더에 있다.
그 경로는 세션 시작 알림 `[HARNESS]` 가 준다. 아래 표만 바꿔 읽고 나머지 절차는 같다.

| 이 문서의 단계·명령 | 플러그인에서 |
|:--|:--|
| 0. 설치 위치 확인 | 건너뛴다 — 훅은 플러그인이 건다 |
| 0-1. git 과 원격 | git 저장소인지만 확인한다. 플러그인은 원격을 요구하지 않는다 |
| `python -X utf8 harness_install.py [옵션]` | `python -X utf8 "<플러그인>/kernel" install [옵션]` |
| `python -X utf8 -m kernel.<모듈> [인자]` | `python -X utf8 "<플러그인>/kernel" <모듈> [인자]` |
| `dev/`·`profiles/` 의 하네스 문서와 서식 | 플러그인 폴더 기준으로 읽는다 |
| `PROJECT.md`·`dev/CONVENTIONS.md` 갱신 | 프로젝트에 그 파일이 없으면 건너뛴다 |
| worktree 자리 제외(`.git/info/exclude`) | 건너뛴다 — 플러그인 코어는 작업 사본을 강제하지 않는다 |

## 0. 설치 위치부터 확인한다 — 다른 무엇보다 먼저

`.claude/settings.json` 의 훅 명령은 `"$(git rev-parse --show-toplevel)/.claude/hooks/…"` 다.
레포 루트에 `.claude/` 가 없으면 훅이 하나도 안 걸리고, **그 상태는 화면에 아무것도 안 남긴다.**
`[SKIP]` 조차 없다 — 검사기가 아예 안 불리기 때문이다.

실제로 났던 사고다. 프로젝트 폴더 안쪽에 `agent-harness/` 로 clone 해서, 하네스 파일은
다 있는데 훅이 하나도 걸리지 않은 채로 시작될 뻔했다.

```bash
git rev-parse --show-toplevel     # 레포 루트
ls .claude/settings.json          # 그 루트에 있어야 한다
```

레포 루트에 `.claude/` 가 없고 하위 폴더에 하네스가 들어 있으면 **내용물을 루트로 올린다.**
`harness_install.py` 가 이 상태를 감지하면 exit 2 로 막고 고치는 명령을 출력한다.

새 프로젝트라면 clone 자체를 프로젝트 폴더로 하는 게 낫다 — `git clone <url> my-project`.

## 0-1. git 과 원격을 연결한다 — 코딩보다 먼저

상태별로 할 일은 공통 조립 절차의 첫 절 「git 과 원격」(`dev/workflows/harness-assembly.md`)을 따른다.
원류에서 막 clone 한 폴더면 `python -X utf8 harness_install.py --new` 가 어느 셸에서든 새 이력과 첫 커밋을 만든다.
origin 이 없으면 `AskUserQuestion` 으로 한 번 고르게 한다: gh 가 인증돼 있으면 그 계정 이름을 보여 주고 "그 계정에 비공개로 만들기", 아니면 "지금 `gh auth login` 하기", 그리고 "이미 있는 레포 주소 알려 주기", "나중에". 나중에를 골라도 과업은 로컬에만 합쳐지며 진행된다.

## 1. 실물을 먼저 본다 — 묻기 전에

질문하기 전에 레포를 훑는다. 이미 답이 있는 것을 묻는 건 시간 낭비고, 사용자는 자기가 뭘
쓰는지 모를 수도 있지만 파일은 안다.

- 최상위 디렉토리와 각각의 파일 확장자
- `requirements.txt`·`pyproject.toml`·`package.json`·`go.mod`·`Cargo.toml` 유무와 내용
- **서버 언어가 무엇인가** — 이게 `SOURCE_EXT`·`SYNTAX` 를 정한다
- 코드가 이미 있는가, 빈 폴더인가

**빈 폴더면 2번으로. 코드가 있으면 스택을 이미 알아낸 것이므로 3번으로 건너뛰고 확인만 받는다.**

## 2. 만들려는 것을 묻는다 — 스택이 아니라

`AskUserQuestion` 으로 묻는다. 선택지는 **기술 이름이 아니라 결과물의 모양**으로 쓴다.

> 무엇을 만드나요?
>
> - **사람이 브라우저로 쓰는 것** — 로그인하고, 화면을 보고, 버튼을 누른다
> - **다른 프로그램이 부르는 것** — 화면 없이 데이터만 주고받는다
> - **혼자 시간표대로 도는 것** — 크롤링, 집계, 리포트 생성
> - **아직 모르겠다** — 만들면서 정하고 싶다

한 번에 다 묻지 않는다. 이 답이 아키텍처 형태(`ARCH`)와 스택 후보를 좁힌다. 더 물어야 할 게 생기면 그때 묻는다.

"아직 모르겠다"면 **가장 흔한 경우로 시작하자고 제안한다** — 화면 있는 웹. 나중에 화면을
안 만들어도 손해가 없다(그 게이트가 `[SKIP]` 될 뿐)고 말해준다. 되돌릴 수 있다는 걸 알려주는
게 초보에게는 선택지를 늘리는 것보다 낫다.

## 3. 후보의 제약을 설명하고 사용자가 고른다

배포되는 프로파일 서식은 스택을 정하지 않은 `_template` 하나뿐이다. 스택은 서식이 아니라 사용자가 정한다.
2번의 답으로 형태를 좁힌 뒤, 언어·프레임워크 후보마다 **이 하네스에서 무엇이 달라지는지**를 말한다.

| 답 | 형태 | 설명할 제약 |
|:--|:--|:--|
| 브라우저로 쓰는 것 | `ARCH = "web_layered"` | 화면 검사는 npm 프로젝트와 `CHECK_PATHS["ui"]` 가 있어야 켜진다. 화면 쪽 언어 검사는 ESLint 에 위임한다 |
| 다른 프로그램이 부르는 것 | `ARCH = "backend_only"` | 화면 검사는 `[N/A]` 다. 나중에 화면을 붙이면 `ARCH` 한 줄로 켠다 |
| 시간표대로 도는 것 | `ARCH = "headless"` | 웹·화면 검사가 `[N/A]` 다. 수집·계산 모듈은 행동 테스트가 짝으로 있는지 검사한다. 조용히 깨지는 코드가 이쪽에 많다 |

언어팩이 들어 있는 언어(`python`·`go`·`typescript`·`java`)는 설치 없이 바로 검사된다. 그 밖의 언어는 4-1 에서 언어팩
하나로 옮겨 붙이고, 그 팩이 1급(`pack_check` 미검증 0)이 될 때까지는 일부 검사가 미검증으로 남는다는 것까지 말해준다.
기존 대화에서 이미 정한 것은 다시 묻지 않는다.

**고르는 사람은 사용자다.** 내 추천이 있으면 근거 한 줄과 함께 붙이되, 사용자가 다른 걸 원하면
그대로 따른다 — 이견이 있으면 1줄로만 말하고 지시를 따른다.

## 4. 깔고 실물에 맞춘다

```bash
python -X utf8 harness_install.py
```

배포본에는 템플릿 프로파일이 이미 있어 `[PROFILE] harness_profile.py already exists — left untouched` 가 정상이다.
검증 출력은 사유가 같은 `[SKIP]` 을 한 줄로 묶어 보인다 — 언어를 고르기 전에는 대부분 건너뛴다.

그다음 `harness_profile.py` 를 1단계에서 본 실물에 맞춘다. **모르는 건 비워둔다.**
비우면 `[SKIP]` 으로 사유와 함께 찍히고, 채우면 켜진다. 억지로 채우면 엉뚱한 경로를
검사해서 오탐만 나온다.

설정 파일(프로파일·`PROJECT.md`·`profiles/`·`docs/architecture/`·`.github/workflows/`)은 본체에서 바로 고친다 —
그래프에 컴포넌트가 없는 설정 단계에는 편집 가드가 이 파일들을 막지 않는다. 과업과 worktree 는 첫 코드부터다.

병렬 작업용 worktree 자리도 이때 git 제외 목록에 올린다. `.git/info/exclude` 는 클론에 전파되지 않으므로
온보딩 말고는 올릴 기회가 없다:

```bash
grep -qx "worktrees/" .git/info/exclude 2>/dev/null || echo "worktrees/" >> .git/info/exclude
```

빼먹으면 worktree 안 파일이 게이트의 검사 대상과 검색 결과에 섞인다. 정본은 `workboard/README.md` 의 작업 격리 절이다. worktree 자리는 루트 `worktrees/` 하나이고, 어느 에이전트든 같은 자리를 쓴다.

**서버 언어가 파이썬이 아니면 `LANG` 부터 적는다.** 이 한 줄로 확장자, 관용구 정규식,
해당 없음 목록, 외부 도구가 모두 정해진다.

```python
LANG = "go"      # kernel/langs/go.py
```

쓸 수 있는 팩은 `--doctor` 첫 줄이 나열한다. 없는 언어는 4-1 의 스택 맞춤에서 템플릿으로 만든다.
같은 언어의 팩이 양쪽에 있으면 프로젝트 쪽이 우선한다. 선언할 것의 목록은 `kernel/lang.py` 헤더에 있다.

확장자가 안 맞으면 대상이 0건이라 나머지를 아무리 채워도 안 돈다. 그래서 이게 먼저다.

### 도구 설치 여부까지 확인한다

```bash
python -X utf8 harness_install.py --doctor
```

언어팩이 위임하는 외부 도구(`go vet`·`staticcheck`·`ruff`·`tsc` 등)와 팩이 `REQUIRES` 로 요구하는 도구, 그리고 구문
분석기(tree-sitter 문법·외부 분석기 명령)가 지금 이 환경에 있는지 찍는다.
**도구가 없으면 그 도구를 쓰는 검사는 `[TOOL]` 로 표시되고 꺼진 채 돈다.** 통과로 처리되지는 않지만 커버리지가
줄어든다. 진단은 그런 누락(훅 인터프리터·git 사용자·검사 도구·분석기)이 하나라도 있으면 exit 1 이고 마지막 줄이 그 수를 말한다.
없으면 설치 명령을 사용자에게 제시하고, 설치할지 물어본다 — 이건 사용자 환경을
바꾸는 일이라 자율로 하지 않는다. 하네스 본체를 개발하는 레포는 아무것도 요구하지 않는다.
사용자가 린터 설치를 원하지 않으면 프로파일에서 그 린터를 뺀다(`LINTERS = []` 또는 남길 것만). 빼지 않으면 `[TOOL]` 이
남아 과업을 끝낼 수 없다. 뺐다는 사실과 무엇이 안 지켜지는지(그 린터의 규칙)를 사용자에게 한 줄로 말한다.

빈 폴더였다면 `CHECK_PATHS` 는 첫 코드의 위치가 정해진 뒤 적는다 — 없는 경로를 미리 적으면 검사 대상이 0건인데도 통과로 표시된다.

## 4-1. 스택을 1급으로 맞춘다 — 끝나는 조건은 `pack_check` 출력이다

고른 언어와 프레임워크마다 팩이 게이트를 **실제로** 켜는지 확인한다. 선언을 적은 것만으로는 1급이 아니고,
판정은 사람이 아니라 `kernel.pack_check` 가 한다. 공통 절차는 `dev/workflows/harness-assembly.md` 「스택 맞춤」이다.

| 순서 | 하는 일 |
|:--|:--|
| 팩 확보 | 커널 탑재 팩이 있으면 쓴다. 없으면 `profiles/lang/_template.py`·`profiles/framework/_template.py` 를 복사해 `profiles/lang/<이름>.py`·`profiles/framework/<이름>.py` 로 만들고 쿼리·패턴·FIXTURES 까지 채운다 |
| 분석기 선택 | 커널 팩(Go·TypeScript·Java)은 설치 없이 정규식 분석기로 돈다(Go 는 tree-sitter 가 있으면 그쪽을 쓴다). 새 중괄호 언어는 `ANALYZER = "regex"` 와 `REGEX`·`MODULE_RULE`·`STDLIB` 부터 쓴다 — 본보기는 `kernel/langs/java.py`. 정규식으로 안 되면 tree-sitter(`QUERIES`)나 `ANALYZER = "command"`(그 언어 자신의 도구로 구문 사실 JSON 을 내는 스크립트, 계약은 `kernel/analyzers/command.py` 헤더)다 |
| 설치 제안 | `--doctor` 가 `REQUIRES` 중 없는 것만 설치 안내와 함께 보고한다. 사용자가 동의한 것만 설치하고, 같은 설치 줄을 `.github/workflows/harness.yml` 의 verify step 앞에도 적는다 — CI 에서 없으면 `[TOOL]` 로 빨갛다 |
| 그래프 바인딩 | 그래프 `technology` 가 프로파일 `LANG` 과 다르면 `graph_schema` 가 결정 대기다. `python -X utf8 -m kernel.graph_workflow bind --syntax <구문> --sources <패턴>… --response "<2~3단계에서 받은 스택 답>" --conversation <대화 참조>` 로 그 답을 결정으로 기록한다 — 다시 묻지 않는다 |
| 루트 파일 | 스택 매니페스트(`go.mod`·`package.json` 등)를 프로파일 `ROOT_FILES` 에 사유와 함께 더한다. 안 더하면 루트 잡파일 검사(45)가 잡는다 |
| 화면 언어 | 화면 레이어(`CHECK_PATHS["ui"]`)를 정하면 `UI_COPY["language"]`(ko·en·ja·zh)를 함께 적는다. 비우면 문구 감수(⑱)가 꺼져 있다고 턴마다 알린다 |
| 1급 판정 | `python -X utf8 -m kernel.pack_check <이름>` 이 `[UNVERIFIED] 0` 이 될 때까지 팩을 고친다 |
| 보고 | 무엇이 `[VERIFIED]` 이고 무엇이 `[N/A]` 이며 왜 그런지 사람 말로 알린다. `[UNVERIFIED]` 가 남았으면 어느 검사가 안 지켜지는지 말한다. 조용히 끝내지 않는다 |

## 5. 검증하고 초록불을 만든다

```bash
python -X utf8 harness_install.py
```

프로파일이 있으면 전 게이트를 `--verify` 로 돌리고 결과를 그대로 돌려준다. **설치는 기존 위반을
자동 동결하지 않는다.** 보고된 위반은 고치는 게 기본이고, 당장 못 고치는 것만 사람이
`harness_baseline.txt` 에 (게이트, 파일) 행으로 옮겨 커밋한다 — 그 파일은 줄이는 것이 원칙이고, 늘면 finish 가 `[RATCHET]` 으로 알린다.
컴포넌트 그래프 검사는 이 동결로 면제되지 않는다.

## 6. 꺼진 게이트를 센다 — 이 단계를 건너뛰지 않는다

```bash
python -X utf8 -m kernel.runner --verify
```

출력의 `[SKIP]` 을 사유로 두 부류로 나눈다.

| 사유 | 하는 일 |
|:--|:--|
| `conditional — …` 로 시작 | 판정하지 않는다. 대상(금칙어·SSL 패치·프롬프트 파일·DDL 등)이 생기기 전에는 켤 것이 없고, 사유가 무엇이 생기면 무엇을 채우는지 말한다. 사용자가 앞으로도 없다고 한 것만 프로파일 `NOT_APPLICABLE` 에 그 말을 사유로 적는다 |
| 그 밖 | 하나씩 판단한다. **채울 수 있다** → 프로파일을 고치고 다시 돌린다. **이 프로젝트엔 해당 없다** → `ARCH` 나 `NOT_APPLICABLE` 로 `[N/A]` 가 되게 한다. **나중에 채운다** → 무엇이 안 지켜지는 상태인지 사용자에게 말한다 |

건너뛰면 하네스를 깔았다는 사실만 남고 무엇이 지켜지는지는 아무도 모른다.

그다음 7-1 로 넘어가기 전에 꼭 돌아야 하는 검사를 `REQUIRED_CHECKS` 로 제안한다(제품 테스트를 선언했으면 `"tests"` 포함). 7-1 뒤에는 본체에서 프로파일을 고칠 수 없다. 기준과 문구는 `dev/workflows/harness-assembly.md` 「스택 맞춤」 끝 문단이 정본이다.

## 7. PROJECT.md 의 첫 문단을 채운다

2단계에서 들은 답을 `PROJECT.md` 의 "무엇을 만드나"에 옮긴다. 한 문단이면 된다.
나머지 표(용어·숫자)는 비워둔다 — 개발하면서 쌓이는 것이지 지금 채우는 게 아니다.

## 7-1. 첫 분류를 기록한다 — 설정 파일 편집이 다 끝난 뒤

제품 코드는 승인된 컴포넌트에 속해야 한다. 빈 폴더면 3번의 스택 확인 질문에 "처음엔 코드를 한 덩어리로 두고
영역이 둘 이상 생기면 나누자고 제안합니다"를 함께 보였으니, 그 답으로 첫 분류를 기록한다 — 첫 코드 앞에서 따로 묻지 않는다.
기록하는 순간 설정 단계가 끝나 프로파일·`PROJECT.md` 를 본체에서 고칠 수 없게 되므로 4~7단계를 먼저 끝낸다.

```bash
python -X utf8 -m kernel.graph_workflow starter --source <코드 폴더> --response "<사용자 답>" --conversation <대화 참조>
```

코드가 이미 있으면 한 덩어리 대신 분류 그래프를 제안한다. 절차는 `dev/workflows/harness-assembly.md`
「첫 분류와 승인」이고 계약은 `dev/COMPONENTS.md` 다. 응답 없는 제안을 승인으로 기록하지 않는다.

## 7-2. 설정을 커밋한다

설정은 본체에서 고쳤으므로 커밋해야 첫 작업 사본에 들어간다. 커밋하지 않으면 `kernel.task start` 가 거절한다.

```bash
git add -A && git commit -m "chore: harness setup"
```

원격이 있으면 push 한다. 없으면 그대로 둔다 — 과업은 로컬에서 합쳐진다.

## 8. 사람 말로 보고한다

숫자만 나열하지 않는다. **지금부터 무엇이 막히는지**를 먼저 말한다. 아래 예시의 개수는 6번 출력에서 센 실제 값으로 채운다.

> 깔았습니다. 이제 파일을 저장할 때마다 검사가 돌고, 어기면 그 자리에서 막힙니다.
> 화면을 아직 안 만들어서 화면 관련 검사는 꺼져 있고, 화면을 만들기 시작하면 켜집니다.
> 기존 코드에서 나온 위반은 목록으로 드렸습니다. 고칠지 동결할지 정하면 되고, 동결한 것은
> 고칠 때마다 목록에서 지웁니다.

그다음 한 줄로 다음 행동을 준다 — 대개 "이제 뭘 만들지 말씀해 주세요"다.

## 경계

프로파일과 설치까지만 한다. 앱 코드는 만들지 않는다 — 그건 기능 작업 스킬의 몫이다.

git 과 원격 연결은 「0-1」 단계가 맡는다.
