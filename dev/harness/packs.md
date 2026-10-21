# dev/harness/packs.md — 팩과 컴포넌트 그래프

> 담는 것: 컴포넌트 그래프 검사와 사용자 결정 기록, 언어팩·프레임워크팩·아키텍처팩의 선언과 구문 사실 분석기. 담지 않는 것: 분류와 승인 기록의 계약(→ [컴포넌트 계약](../COMPONENTS.md))·번호 붙은 게이트 표(→ [하네스 지도](../HARNESS.md)). 읽는 시점: 새 언어나 프레임워크를 붙일 때, 그래프 검사 결과를 읽을 때.

## 컴포넌트 그래프와 사용자 결정

[컴포넌트 계약](../COMPONENTS.md)이 분류와 승인 기록의 정본이다.
첫 분류는 설정 때 `python -X utf8 -m kernel.graph_workflow starter --source <폴더> --response "<설정 답>" --conversation <참조>` 가 코드 전체를 planned 컴포넌트 `app` 하나로 기록한다 — `bind` 처럼 사용자가 이미 한 답을 결정으로 남긴다. 나누기는 영역이 둘 이상 생길 때 plan 의 「분류 제안」 행이 맡는다.
AI는 분류되지 않은 변경을 찾으면 구체적인 분류 제안과 함께 사용자에게 알린다.
사용자가 대화에서 실제로 한 답변을 변경안에 기록하며, 호스트 전용 알림 API는 필요하지 않다.
로컬 기록 검사는 일관성을 확인하며 사용자 신원을 인증하지 않는다.

그래프 검사는 [하네스 지도](../HARNESS.md) 「게이트」의 번호 붙은 게이트 목록과 별도로, 번호 대신 이름으로 식별한다.

그래프의 `technology`(구문과 소스 패턴)는 프로파일 `LANG` 과 같아야 한다. 어긋나면 `graph_schema` 가 결정 대기(`needs_decision`)이고,
`python -X utf8 -m kernel.graph_workflow bind --syntax <구문> --sources <패턴>… --response "<스택 답>" --conversation <참조>` 가
승인된 컴포넌트는 그대로 둔 채 `technology` 만 바꾼 제안을 만들어 이미 받은 스택 답을 결정으로 기록한다 — 다시 묻지 않는다.
제품 소스와 구현 완료 컴포넌트가 둘 다 없으면 분류·의존·구문 검사는 `[SKIP]`(대상 0건)이다. 대상이 없는데 `[OK]` 로 찍지 않는다.

| 검사 이름 | 책임 | 판정 정본 |
|---|---|---|
| graph_schema | 그래프 서식과 참조 유효성, 프로파일 언어와의 바인딩 | `kernel/component_graph.py` · `kernel/graph_checks.py` |
| component_classification | 제품 코드마다 소유 컴포넌트가 하나뿐인지와 그 역할 | `kernel/gates/components.py` |
| graph_approval | 제안과 실제 대화 결정 기록의 일치 | `kernel/graph_workflow.py` |
| component_dependencies | 허용 의존과 공개 계약 | `kernel/gates/context_api.py` |
| component_syntax | 분석할 수 없는 구문의 미검증 표시. 소유자가 하나가 아닌 파일은 결정 대기라 여기서 세지 않고, 그 파일로 가는 import 는 분류가 정해진 뒤 판정한다 | `kernel/gates/context_api.py` |
| graph_projection | 정본과 생성 지도의 일치 | `kernel/feature_map.py` |
| port_contracts | 선언한 포트의 실제 실행 계약 | `kernel/port_contracts.py` |
| port_tools | 포트 검사를 실행하지 못한 원인 — 포트를 선언했는데 Python 분석기가 아닐 때만 | `kernel/port_contracts.py` |

포트를 선언한 경계에만 테스트 대역과 실행 계약을 요구한다. 포트를 선언하지 않은 그래프는 언어와 무관하게 미검증을 내지 않는다.
테스트 대역은 이름만 확인하지 않고 실제 계약 테스트를 실행한다.
검사기는 정본이나 제안 상태를 수정하지 않는다.
제안과 알림 상태 변경은 워크플로가 담당한다.

## 언어팩

팩 축은 셋이다. 언어팩(`LANG`)은 검사기가 그 언어를 이해하는 방법, 아키텍처팩(`ARCH`)은 어떤 레이어가 있는가, 프레임워크팩(`FRAMEWORK`)은 웹·화면 게이트가 읽을 프레임워크 선언이다.

하네스의 Python 실행 환경은 제품 언어를 결정하지 않는다.
LANG을 선택하기 전에는 소스 확장자와 구문 분석을 임의로 Python으로 채우지 않는다.
새 프로젝트는 스택을 정하지 않은 프로파일 서식 하나에서 시작하며 [조립 절차](../workflows/harness-assembly.md)를 따른다.
언어팩은 소스 확장자와 관용구와 위임할 도구를 선언한다.
구문 사실을 뽑는 tree-sitter 쿼리와 모듈 키·공개 이름 규칙과 적합성 예제도 같은 팩이 선언한다 — 선언 목록의 정본은 `kernel/lang.py` 헤더다.
알 수 없는 팩 이름이나 깨진 팩은 설정 오류로 보고한다.
구문 분석기를 지원하지 않는 언어는 미검증으로 남긴다.
Python 의미론에만 있는 게이트(`kernel/lang.py` `PYTHON_ONLY` — 32·38)는 비 Python 팩이 `NOT_APPLICABLE` 에 그 언어에서 성립하지 않는 사유와 함께 선언한다. 러너가 `SYNTAX` 만 보고 알아서 빼지 않는다 — 사유가 팩마다 다르다. 빠뜨린 팩은 `pack_check` 가 `[UNVERIFIED]`, 러너가 선언하라는 `[TOOL]` 로 알린다.
외부 도구의 비정상 종료를 빈 진단 목록만으로 성공 처리하지 않는다.

### 구문 사실 — 게이트는 `ast` 를 보지 않는다

중첩 def(2)·함수 길이(37)·타입힌트(8)·선언 본문 중복(34)·이름 일관성(48)·MD 함수 참조(33)와 컴포넌트 의존 방향(`component_dependencies`)은 파일마다 한 번 뽑아 둔 구문 사실(함수·import·최상위 이름 같은 구문 정보, 정의는 `kernel/facts.py`)만 읽는다. 구문 사실을 만드는 것은 분석기이고, 언어를 아는 것도 분석기뿐이다. 그래서 하네스를 새 언어로 옮기는 일은 분석기가 읽을 선언(언어팩)을 쓰는 일이다.

어느 분석기를 쓸지는 언어팩의 `ANALYZER` 가 정하고, 비어 있으면 `SYNTAX` 로 추정한다(python → `python`, 그 밖에 `QUERIES` 가 있으면 `treesitter`, `REGEX` 만 있으면 `regex`). `QUERIES` 와 `REGEX` 를 함께 선언한 팩은 tree-sitter 가 설치되지 않았을 때 `regex` 로 내려간다 — 쿼리 컴파일 오류는 내려가지 않고 팩 결함으로 보고한다.

| 분석기 | 실물 | 설치 |
|---|---|---|
| `python` | `kernel/analyzers/python.py` — 표준 `ast` | 없음 |
| `regex` | `kernel/analyzers/regex.py` — 팩 `REGEX` 로 함수 머리·import·최상위 이름을 찾고, 주석·문자열을 지운 본문에서 함수 머리 뒤 `{` 의 짝을 범위로 삼는다. 중괄호가 맞지 않으면 그 파일은 `error` | 없음. Go·TypeScript·Java 팩이 이것으로 돈다 |
| `treesitter` | `kernel/analyzers/treesitter.py` — 팩의 `QUERIES` 실행 | `tree-sitter` 와 팩 `GRAMMAR` 문법 패키지. 없으면 `REGEX` 로 내려가고, 그것도 없으면 `[TOOL]` |
| `command` | `kernel/analyzers/command.py` — 팩 `ANALYZER_CMD` 가 낸 구문 사실 JSON 을 계약으로 검증 | 그 언어의 툴체인. 명령의 상대경로는 프로젝트 루트 기준이다. 명령이 없으면 `[TOOL]`, 출력이 계약과 다르면 그 파일은 `error`(통과 아님) |

import 를 레포 모듈로 푸는 규칙(`MODULE_RULE`)은 `kernel/analyzers/modules.py` 하나를 tree-sitter·정규식 두 분석기가 같이 쓴다 — `go_package`(가장 가까운 `go.mod`), `relative`(`./x`·`../y`, `/index` 는 폴더 키), `dotted`(`a.b.C`·`crate::a::b` 를 레포 모듈 키의 접미로). 표준 라이브러리는 팩 `STDLIB` 가 정하고, 컴포넌트 `external` 의 `"*"` 는 모든 외부 의존을 허용한다(첫 분류 `starter` 가 쓴다).

Python 의미론에만 있는 판정(속성 경유 참조·동적 import·domain 부수효과)의 재료는 Python 분석기의 `extra` 로만 전달되고, 다른 언어에서는 그 부분을 건너뛴다.
프레임워크 판정(13·16)과 미정의 상수(32)는 아직 Python `ast` 다. 13·16 은 서버 프레임워크팩이 판정 방식(`ASYNC_HANDLER`·`ERROR_STATUS_KWARG`)을 선언했을 때만 돌고, 다른 언어에서는 설치 사유가 아니라 "분석기 없음"으로 찍힌다. 32 는 `PYTHON_ONLY` 라 팩 선언으로 `[N/A]` 가 된다. 포트 검사는 포트를 선언했을 때만 Python 분석기를 묻는다.

팩이 1급인지는 선언이 아니라 `python -X utf8 -m kernel.pack_check <이름>` 이 판정한다.
팩의 `FIXTURES` 로 위반 예제가 잡히고 통과 예제가 안 잡혀야 `[VERIFIED]` 이고, `[UNVERIFIED]` 가 하나라도 있으면 exit 1 이다.
새 언어·프레임워크는 `profiles/lang/_template.py`·`profiles/framework/_template.py` 를 복사해 만들고, 초기 설정의 「스택 맞춤」([조립 절차](../workflows/harness-assembly.md))이 이 명령으로 1급을 확인한다.

팩의 `REQUIRES` 는 1급으로 돌기 위한 외부 도구의 확인 명령과 설치 안내다. `harness_install.py --doctor` 가 린터 설치 여부, 고른 분석기의 가용성, 미충족 `REQUIRES` 를 보고하고, 설치는 사용자가 정한다. 하네스 자신의 프로파일은 아무것도 요구하지 않는다.

## 프레임워크팩

언어팩·아키텍처팩 옆의 세 번째 팩 축이다. 웹·화면 게이트의 판정은 `kernel/gates/` 와 `kernel/eslint.harness.mjs` 에 한 벌뿐이고, 프레임워크마다 다른 **선언**만 팩에 둔다. 프로파일의 `FRAMEWORK` 가 역할별로 최대 하나씩 고른다.

| 역할 | 선언 | 읽는 게이트 |
|---|---|---|
| `server` | 라우트 정규식, await 없는 async 판정 방식, 스트림 반환 타입, 에러 상태 키워드, 래퍼 대신 허용할 응답 타입, 라우터 접두 정규식, 기반 라우트 | 13 · 16 · 31 |
| `ui` | 화면 소스 패턴, ESLint 파서와 옵션(확장자별 파서 `PARSERS`), 설치 안내, 테스트 짝 확장자와 진입 표식, 한 주인 기능(`OWNED`) | 10 · 17~20 · 42 · 43 · 44 · 49, 그리고 `UI_EXT` 기본값 |

- 로더는 `kernel/framework.py`. 선언 목록의 정본은 그 헤더다. 같은 이름을 `profiles/framework/<이름>.py` 에 두면 프로젝트 것이 이긴다.
- 기본 탑재 팩 두 개(`kernel/frameworks/`)는 이 하네스가 처음 쓰인 프로젝트의 동작을 그대로 옮긴 것이라, 그 둘을 고른 프로젝트의 게이트 출력은 도입 전과 같다(골든으로 고정).
- 팩을 안 고르면 그 역할의 게이트는 `[SKIP] … no server framework pack selected` 류다. 조용히 통과하지 않는다.
- 팩이 판정 방식을 선언하지 않으면 `[N/A] <팩>: does not apply to this framework` 다. 못 함과 해당 없음을 가르는 것이 언어팩과 같은 경계다.
- 역할 중복·모르는 이름·틀린 선언은 프로파일 오류(검사 47)다.
- 1급 여부는 `kernel.pack_check` 가 판정한다. 서버팩은 라우트 예제(route·consumer·stranger)로, 화면팩은 ESLint 실측으로 잰다. ESLint 가 없는 환경의 화면 예제는 `[UNVERIFIED]` 에 eslint 설치 안내가 붙는다.
- `PROFILE_SCHEMA` 는 올리지 않았다. `FRAMEWORK` 는 선택 항목이라 기존 프로파일은 `[SKIP]` 사유로 새 항목을 알게 된다.

팩은 판정 선언(`<이름>.py`) 옆에 사람용 관례 조각(`<이름>.md`)을 둔다. 초기 설정의 스택 맞춤이 `FRAMEWORK` 가 고른 조각을 `python -X utf8 -m kernel.conventions` 로 `dev/CONVENTIONS.md` 「스택 관례」 절에 넣는다. 절은 표식 주석 사이에 있고 손으로 고치지 않는다 — 고칠 것은 조각이다. 같은 이름의 `profiles/framework/<이름>.md` 가 있으면 프로젝트 것이 이긴다.

## 아키텍처팩

언어팩과 같은 골격을 아키텍처 축에 복제한 것이다. 프로파일의 `ARCH` 한 줄이
`kernel/archs/<이름>.py` 를 고르고, 거기 선언된 `NOT_APPLICABLE`(성립하지 않는 게이트와
사유)이 따라온다. 화면 없는 서비스의 UI 게이트가 `[SKIP]`(설정을 안 채움)이 아니라
`[N/A]`(아키텍처상 채울 것이 없음)로 찍히게 하는 것이 존재 이유다.

| 팩 | 뜻 | `[N/A]` 로 도는 것 |
|----|----|----|
| `web_layered` | 화면+서버 풀스택 | 없음 — 전 게이트 성립 |
| `backend_only` | 서버는 있고 화면이 없다 | 화면 게이트 11종 — 6·10·17~20·24·31·42~44 |
| `headless` | 웹도 화면도 없다 — 배치·CLI·라이브러리 | 위 11종 + 웹 2종(13·16) |

- 로더는 `kernel/arch.py`. 같은 이름을 `profiles/arch/<이름>.py` 에 두면 프로젝트 것이 이긴다.
- `ARCH` 미선언이면 아무것도 `[N/A]` 로 돌리지 않는다 — 도입 전 프로파일의 동작 그대로다.
- N/A 사유 병합은 언어팩 → 아키텍처팩 → 프로파일 순이고 나중이 이긴다. 출처 접두(`go:`·`headless:`)는
  `kernel/profile.py` 병합 시점에 붙는다 — 러너는 그대로 찍는다.
- 게이트 판정 코드는 옮기지 않았다. 팩은 선언이고 판정은 `kernel/gates/` — 언어팩과 같은 경계다.
- DB 계열 게이트는 어느 팩에도 없다 — 배치·라이브러리도 DB 를 가질 수 있어 "정의상 부재"가 아니다.
  프로젝트별 부재는 프로파일 `NOT_APPLICABLE` 이 담당한다.

설치 상태 점검은 `python -X utf8 harness_install.py --doctor` 다. 훅 인터프리터(`python`·`python3`)·git 사용자·검사 도구·분석기처럼 훅이나 `--verify` 를 멈추게 할 것이 빠지면 exit 1 이고(`kernel/preflight.py`), gh·원격은 정보로만 찍는다. 새 프로젝트의 첫 커밋은 어느 셸에서든 `python -X utf8 harness_install.py --new` 다(`kernel/fresh_repo.py` — 원류에서 막 clone 한 이력만 지운다).
