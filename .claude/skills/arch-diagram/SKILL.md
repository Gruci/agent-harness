---
name: arch-diagram
description: 아키텍처·흐름·시퀀스·데이터플로·상태기계 그림을 정본 JSON 으로 쓰고 소스 증거를 붙여 렌더한다. "아키텍처 그려줘"·"흐름도"·"순서도"·"시퀀스 그려줘"·"다이어그램 갱신"·"구조 바뀐 거 보여줘" 요청, plan 의 아키텍처 델타 항목, harness-init 의 첫 그림 단계에서 반드시 이 스킬을 사용할 것. 검증 없는 그림은 만들지 않는다.
---

# arch-diagram — 검증되는 그림

> 담는 것: 정본 JSON 작성 → validate 루프 → deliver → 델타 → 보고의 절차. 담지 않는 것: 그림 규약과 그림 1:1 대조 검사인 검사 48(→ `dev/DIAGRAM.md`), 필드와 배치와 수리 규칙(→ `dev/DIAGRAM_AUTHORING.md`). 읽는 시점: 그림을 만들거나 고칠 때.

**먼저 `dev/DIAGRAM.md` 와 `dev/DIAGRAM_AUTHORING.md` 를 Read 한다.** 작성 예시는 하네스 자신의 그림 `docs/architecture/harness.architecture.json` 이다.

## 1. 타입과 이름을 정한다

레이어 지도면 `architecture`, 훅·배치·승인 흐름이면 `workflow`, 요청 한 번의 여정이면 `sequence`, 파이프라인이면 `dataflow`, 상태 전이면 `lifecycle` 을 고른다. 파일 경로는 `docs/architecture/<이름>.<타입>.json` 이다.

## 2. 정본을 쓴다 — 소스 증거까지

- 첫 architecture 는 컴포넌트 그래프(`docs/architecture/components.json`)의 implemented 컴포넌트에서 노드를 만든다. 열은 그래프 간선의 의존 방향을 따른다. 격자는 열 간격 260, 행 간격 180이고 노드 크기는 `[170, 64]` 다.
- `external` 이 아닌 모든 노드에 `sources` 를 적는다. 파일과 행 범위는 **Read 로 확인한 것만 적는다.** 추측으로 적지 않는다. 샘플 데이터가 있으면 `label: "샘플"` 항목으로 가리킨다.
- `meta.repository` 에는 `git remote get-url origin` 과 `git rev-parse HEAD` 의 값을 적는다. `sources` 가 가리키는 파일은 그 커밋에 있어야 하므로, 새 파일이면 코드를 먼저 커밋한다.
- `meta.views` 에 챕터를 2~5개 둔다.

## 3. validate 루프

```bash
python -X utf8 -m kernel.diagram validate <타입> docs/architecture/<이름>.<타입>.json
```

진단의 `subject`·`evidence`·`supportedFixes` 가 짚은 곳만 고치고 다시 돌린다. 수리 순서와 멈춤 규칙은 `dev/DIAGRAM_AUTHORING.md` 에 있다. `[TOOL] node 없음` 이 나오면 사용자에게 node 설치를 안내하고 멈춘다. 이 상태를 통과로 처리하지 않는다.

## 4. deliver — 최종 한 번

```bash
python -X utf8 -m kernel.diagram deliver <타입> docs/architecture/<이름>.<타입>.json
```

HTML 과 `.svg` 와 `.receipt.json` 이 생긴다. 정본, HTML, SVG, 영수증 네 파일을 함께 `git add` 한다. deliver 를 통과한 정본은 이후 손대지 않고, 손댔다면 deliver 를 다시 돌린다. 훅이나 게이트를 바꿨으면 `python -X utf8 -m kernel.diagram rules` 로 규칙 지도도 다시 만든다. 규칙 지도의 정본은 손으로 고치지 않는다.

## 5. 델타 — 구조가 바뀌는 plan 일 때

```bash
git show HEAD:docs/architecture/<이름>.architecture.json > <scratchpad>/base.json
python -X utf8 -m kernel.diagram compare <scratchpad>/base.json docs/architecture/<이름>.architecture.json docs/tasks/arch_delta.html
```

plan 에는 산출물 경로와, 추가·제거·변경된 노드와 엣지의 수를 적는다. architecture 가 아닌 타입은 정본의 git diff 로 델타를 적는다.

## 6. 보고

`dev/DIAGRAM.md` 의 완료 보고 서식을 따른다. deliver 통과와 "HTML 을 열어 봤는가"는 별개 주장이라 따로 적는다. 그림 1:1 대조 검사(검사 48)가 세션 종료 때 모든 항목을 다시 확인한다.

## 경계

그림만 만든다. 코드는 건드리지 않는다. 좌표는 진단이 지적한 만큼만 고친다. 좌표를 글로 미리 계획하지 않는다.
