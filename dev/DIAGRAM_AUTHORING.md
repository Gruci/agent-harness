# dev/DIAGRAM_AUTHORING.md — 그림 작성 계약

> 담는 것: 정본 JSON 을 쓸 때 지킬 스키마 요약·불변조건·간격 계산·수리 순서·타입별 배치 규칙·진단 소비법. 담지 않는 것: 왜 그리나·1:1 매핑·검사 48(→ `dev/DIAGRAM.md`)·절차(→ `arch-diagram` 스킬). 읽는 시점: 정본 JSON 을 쓰거나 고치기 직전.

스키마 실물은 `kernel/diagram/engine/schemas/` 다. 모든 스키마가 `additionalProperties: false` 라 모르는 필드는 거절된다. 필드를 새로 지어내지 말고 `docs/architecture/` 에 있는 하네스 그림 4장을 서식 예시로 삼는다.

## 공통 골격

| 필드 | 값 |
|:--|:--|
| `schema_version` | architecture·sequence·dataflow·lifecycle 는 `1`, workflow 는 `2` |
| `diagram_type` | 타입 이름 |
| `meta.title` | 짧은 제목 하나. 그림이 설명을 맡는다 |
| `meta.quality_profile` | `"showcase"` 가 기본. 9/9 통과가 완성 기준이다. `standard` 는 조밀한 지도를 명시 요청받을 때만 |
| `meta.repository` | `url`·`revision`. 소스 증거가 있으면 필수 |
| `meta.views` | 최대 5개. `{id, label, focus[노드 id], note}` — 읽는 사람의 챕터 |
| 생략이 기본 | `subtitle`(제목을 되풀이하지 않는다), `legend`(auto), `visual_preset`(classic), `locale`(한국어 팩이 없어 뷰어 UI 는 영어다) |

노드 `type` 은 `frontend`·`backend`·`database`·`cloud`·`security`·`messagebus`·`external` 이다. 관계 `variant` 는 `default`·`emphasis`·`security`·`dashed` 이고 sequence 는 `return` 이 더 있다. `id` 는 `^[a-zA-Z][a-zA-Z0-9_-]*$` 이고 컬렉션 안에서 유일하다.

## 타입별 구조 배열

| 타입 | 노드 | 관계 | 그 밖에 |
|:--|:--|:--|:--|
| architecture | `components` — `pos [x,y]`·`size [w,h]` 자유 좌표 | `connections` | `boundaries` — `kind` 는 `region`·`security-group` 둘뿐 |
| workflow v2 | `nodes` — `lane`·`col 0..5`·`width` | `edges` | `lanes`·`phases`·`groups`·`mainPath`·`semanticChecks` |
| sequence | `participants` | `messages` — `y` 좌표 | `segments`·`activations`·`meta.column_fit` |
| dataflow | `nodes` — `stage`·`row` | `flows` — `classification` | `stages` |
| lifecycle | `states` — `type` 은 `start`·`active`·`waiting`·`decision`·`success`·`failure`·`neutral`·`external` | `transitions` | `lanes` |

## 불변조건

- 주 경로는 하나다. 가지는 가장 가까운 주 경로 노드에서 나간다. 라우팅 컨트롤을 더하기 전에 가치 낮은 엣지를 먼저 뺀다.
- 주요 노드는 12개가 상한이다. 넘으면 그림을 나누되, 그 전에 컴포넌트 단위(입도) 규칙을 지켰는지 먼저 본다.
- 자동 라우트·자동 라벨로 시작한다. `via`·`channelX`·`channelY`·`labelAt`·`labelDx`·`labelDy` 는 **진단이 요구할 때 하나씩** 넣는다. 한 번의 수리에 컨트롤 하나.
- 관계 라벨은 의미 데이터다. 겹치면 옮기고, 라우트·간격을 조정하고, 그다음에야 뜻을 지키며 줄인다. 양끝 노드만으로 뜻이 다 드러나는 라벨만 생략한다. **삭제는 수리가 아니다.**
- side 는 방향 계약이다. `fromSide: "bottom"` 이면 첫 세그먼트가 아래로 나간다.
- 엣지가 무관한 불투명 노드를 가로지르거나, 모호한 공유 복도를 타거나, 라벨이 다른 라우트를 가리면 showcase 는 실패한다.
- 제품명·식별자·명령·경로는 원문 그대로. 설명 산문은 한국어.

## 간격 계산

간격은 중심 거리가 아니라 **빈 틈**이다. 165px 상자 둘의 중심이 200px 떨어지면 틈은 35px 이다.

```text
빈 틈 > 라벨 마스크 폭 + 8px
라벨 마스크 폭 ≈ 6.5px × ASCII 단위 + 13px   (CJK 한 글자는 2단위)
```

architecture 첫 배치 격자: 열 간격 260, 행 간격 180, 크기 `[170, 64]`. 1440px 폭에서 글자가 읽혀야 하므로 전체 폭은 1300 안쪽으로 둔다 — 넘으면 `composition/desktop-readability` 로 실패한다.

## 수리 순서 — 진단이 나오면 이 순서대로

1. `meta.quality_profile` 누락·오타와 스키마 오류.
2. 노드 겹침·범위 밖 배치.
3. 엣지가 노드를 가로지름·끝점 방향 위반.
4. 교차·모호한 복도·경계선 따라가기·라우트 리듬(세그먼트 8px·내부 16px).
5. 라벨 ↔ 노드, 라벨 ↔ 라벨, 라벨 ↔ 라우트 간격.

매 수정 뒤 `validate` 를 돈다. 진단의 `subject`·`evidence`·`supportedFixes` 가 가리키는 것만 고친다. 진단이 `labelAt` 좌표를 주면 그 값을 쓴다. **오류 수가 새 최저를 갱신하는 동안 계속하고, 두 라운드 연속 개선이 없으면 멈추고 남은 진단을 그대로 보고한다.** 렌더러 소스를 읽는 것은 지원되지 않는 진단을 만났을 때뿐이다.

## 타입별 배치

- **architecture** — 왼쪽에서 오른쪽으로 이어지는 중심축 하나에 짧은 세로 가지를 붙인다. 노드는 6~12개. 경계는 실제 소유·신뢰·배포 경계에만 그린다. 외부 행위자는 경계 밖에 둔다.
- **workflow v2** — `col` 은 0..5 의 논리 순위이고 좌표는 컴파일러가 잰다. `mainPath` 는 연속 노드 사이에 실제 엣지가 있어야 한다. 예외 레인은 `variant: "exception"`. 라벨이 노드보다 넓으면 `width` 를 늘린다.
- **sequence** — `y` 는 위에서 아래로 증가. `segments` 로 구간 이름. 넓은 viewBox 에 여백이 남으면 `meta.column_fit: "spread"`.
- **dataflow** — `stages` 순서가 곧 흐름. `classification` 으로 PII 같은 성격을 표시.
- **lifecycle** — 주 경로는 열 0..4 에 둔다. 복구 가능한 실패는 `type: "failure"` 에 활성 상태로 돌아가는 실제 전이를 둔다.

## 델타·뷰 작성

`meta.views` 의 `focus` 에는 실제로 있는 노드 id 만 넣는다. 챕터는 "정상 경로 → 예외 경로 → 산출물" 순이 읽기 좋다. compare 는 architecture 만 지원한다 — 다른 타입의 델타는 정본 JSON 의 git diff 로 노드·엣지 추가·제거를 적는다.
