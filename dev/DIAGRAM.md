# dev/DIAGRAM.md — 아키텍처·흐름 그림의 정본 규약

> 담는 것: 그림을 왜·어디에·어떤 입도로 두고, 노드와 소스 코드를 어떻게 1:1 로 묶으며, 검사 48 이 무엇을 보는지. 담지 않는 것: 필드 enum·배치·수리 규칙(→ `dev/DIAGRAM_AUTHORING.md`)·작성 절차(→ `arch-diagram` 스킬). 읽는 시점: 그림을 만들거나 고치기 전, 그리고 plan 의 아키텍처 델타를 쓰기 전.

## 왜 그리나 — 검증되는 그림만 그림이다

구조를 뜯어고치거나 통합할 때 "어디가 어떻게 바뀌나"를 코드 스니펫이 아니라 그림으로 본다. 그런데 그림은 코드와 어긋나는 순간 산문이 된다. 그래서 이 하네스의 그림은 셋을 만족해야 존재한다.

| 조건 | 어떻게 |
|:--|:--|
| 정본이 git 에 있다 | `docs/architecture/<이름>.<타입>.json` — 타입드 JSON. 렌더된 HTML 은 산출물이다 |
| 상자마다 코드 위치가 증명된다 | 노드의 `sources` 가 파일·행 범위를 가리키고, 엔진이 커밋 기준으로 blob 과 행 수를 검증한다 |
| 어긋나면 기계가 잡는다 | 검사 48 — 이름을 바꾸고 그림을 안 고치면 세션이 안 끝난다 |

엔진은 `kernel/diagram/engine/`(MIT 재조립본) 이고, 노출은 `python -X utf8 -m kernel.diagram` 이다. 원류·변경 내역은 그 디렉토리의 THIRD_PARTY_NOTICES 가 정본이다 — 하네스 문서는 원류 이름을 쓰지 않는다.

## 타입 5종 — 언제 무엇을

| 타입 | 하네스 용례 | 노드 컬렉션 |
|:--|:--|:--|
| `architecture` | 컴포넌트 지도. 프로젝트마다 최소 한 장 | `components` |
| `workflow` | 훅 발화 순서·배치 파이프라인·승인 흐름. 가이드 뷰로 재생한다 | `nodes` |
| `sequence` | 요청 한 번의 여정 — 화면 → 라우트 → 조회 → 응답 | `participants` |
| `dataflow` | 수집 → 가공 → 적재 파이프라인과 소비처 | `nodes` |
| `lifecycle` | 상태기계 — 과업·worktree·주문의 상태 전이 | `states` |

**입도는 컴포넌트다.** 파일·함수 단위는 그리지 않는다. 컴포넌트가 하나 늘면 노드 하나, 의존이 하나 늘면 엣지 하나 — 그래서 "그림만 고치면 된다"가 성립한다. 좌표를 사람이 정하는 엔진이라 노드가 늘수록 배치 비용이 커지고, 입도 규칙이 그 상한이다.

## 파일 규약

```
docs/architecture/
  <이름>.<타입>.json           정본
  <이름>.<타입>.html           deliver 산출물 — 커밋한다. 보는 쪽은 아무것도 설치하지 않는다
  <이름>.<타입>.svg            같은 렌더에서 뽑은 독립 SVG — README 가 싣는다. GitHub 은 HTML 을 안 그린다
  <이름>.<타입>.receipt.json   하네스 영수증 — 커밋한다. 검사 48 이 정본 해시와 대조한다
```

`rules.workflow.json` 은 예외로 **생성물**이다. `python -X utf8 -m kernel.diagram rules` 가 `.claude/settings.json` 배선과 러너 게이트 목록에서 만들고 바로 deliver 한다. 훅·게이트가 바뀌면 다시 돌린다 — 손으로 고치지 않는다.

영수증은 엔진 receipt 를 감싼 것이고 `spec_sha256_lf`(정본의 LF 정규화 해시)·`revision`(deliver 시점 HEAD)·`validation` 을 갖는다. 정본만 고치고 deliver 를 안 하면 해시가 어긋나 걸린다.

## 1:1 매핑 — 가장 중요한 축

노드에 `sources` 를 적는다. 다섯 타입 전부 같은 모양이다.

```json
{ "id": "runner", "type": "backend", "label": "러너", "sublabel": "kernel/runner.py",
  "sources": [ { "path": "kernel/runner.py", "line": 367, "end_line": 400, "label": "main" } ] }
```

- `meta.repository` 에 `url`(origin) 과 `revision`(40자 커밋) 을 적는다. 엔진이 그 커밋의 blob 과 행 수로 검증하므로 **아직 커밋 안 된 파일은 가리킬 수 없다.** 순서는 코드 커밋 → deliver → 그림 커밋이다.
- `sources` 는 노드당 최대 3개다. 하나는 "이 상자가 곧 이 코드"이고, 나머지는 진입점이나 **샘플 데이터** 다 — 픽스처·응답 예시 파일을 `label: "샘플"` 로 가리키면 뷰어의 패스포트에서 바로 연다.
- `type: external` 노드(사람·외부 시스템)와 `lifecycle` 의 상태는 코드 대응물이 없어 면제다. 나머지는 전부 있어야 한다.
- `revision` 은 deliver 가 찍는다. 이후 커밋이 쌓이면 검사 48 이 "원류가 바뀜" 을 REPORT 로 말하고, 그림을 손볼 때 deliver 가 다시 찍는다. 작성 시점(`--file`)엔 검사 48 이 돌지 않는다 — 전량 대조라 비교 상대가 없다.

뷰어에서는 노드를 누르면 패스포트가 열리고 SRC 마커가 revision 고정 링크로 파일·행을 연다. 원류가 GitHub 이면 웹 링크, 아니면 `link_mode: local-only` 로 경로만 검색된다.

## 검사 48 — 무엇을 보나

| 판정 | 근거 | 등급 |
|:--|:--|:--|
| 면제 아닌 노드마다 `sources` 1개 이상 | 코드 어디인지 모르는 상자는 산문이다 | FAIL |
| implemented 컴포넌트마다 그 root 를 가리키는 노드 (architecture) | 컴포넌트 그래프의 implemented 집합 ↔ 그림 커버리지. planned 는 제외 | FAIL |
| 모든 `path` 가 작업 트리에 실존, 행 범위가 파일 안 | 이름 바꾸고 안 고침 | FAIL |
| `revision` 이 이 레포의 커밋 | 남의 커밋 | FAIL |
| 영수증 해시 = 현재 정본, HTML 실존 | 렌더 안 한 정본 | FAIL |
| `revision` 이후 원류가 바뀐 노드 — `label: 샘플` 은 데이터라 제외 | 재검토 신호 — 오탐 여지가 있어 합산 안 함 | REPORT |
| 엔진 `validate --repo-root` 의 diagnostics | 스키마·배치·증거의 정본 판정. 영수증 해시가 정본과 같으면 deliver 가 이미 통과시킨 것이라 재호출하지 않는다. 그 외엔 node 없으면 `[TOOL]` | FAIL / TOOL |

greenfield 에서 그림이 없으면 `[SKIP] 아직 없음` 이다. growing 이상에서 없으면 그 자체가 위반이다 — 코드가 자란 프로젝트에 그림이 없는 건 손실이다.

## 델타 — 구조가 바뀌는 plan

컴포넌트·의존 방향이 바뀌는 과업은 plan 에 아키텍처 델타를 적는다. 정본을 먼저 고치고 `python -X utf8 -m kernel.diagram compare <base> <head> docs/tasks/arch_delta.html` 로 before·delta·after 를 만든다. `<base>` 는 `git show HEAD:<정본 경로>` 로 고치기 전 정본을 스크래치에 받은 JSON, `<head>` 는 고친 정본이다. 승인자는 코드가 아니라 그림으로 "이 변경이 구조를 어디로 미는가"를 본다. 완료 시 델타 HTML 은 research·plan 과 같은 archive 폴더로 간다. 안 바뀌면 "미발동" 한 줄이다.

## 뷰어가 이미 하는 것 — 작성 비용 0

생성 HTML 에 들어 있다. `meta.views`(최대 5개 챕터) 만 적으면 나머지는 읽는 사람의 몫이다.

- 가이드 뷰 · 프레젠테이션(`?present=1`) · 재생(`&play=1`) · 챕터 딥링크(`#view=<id>`)
- 노드 검색 · 포커스 · 상류·하류 추적 · 두 노드 사이 루트 탐색(`#route=a~b`)
- 시맨틱 패스포트 — 노드의 관계·소스 증거·샘플 링크
- 다크·라이트 · PNG/SVG/WebM 내보내기 · 공유 카드

## 완료 보고 서식

deliver 는 결정론적 검증만 증명한다. 렌더된 HTML 을 열어 봤는지는 별개 주장이다 — 원칙 2·2-1.

```text
diagram: <이름>.<타입> · validation: 9/9 showcase, 0 errors, 0 warnings
revision: <7자> · 렌더 HTML 확인: 봤음 | 안 봤음 · 수정 라운드: n
```

"봤음" 은 실제로 열어 본 경우에만 쓴다.
