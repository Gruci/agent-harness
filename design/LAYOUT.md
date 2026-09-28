# design/LAYOUT.md — 레이아웃·간격·그리드

> 담는 것: 화면 골격과 간격 체계, sticky 패턴의 결정 근거. 담지 않는 것: 브레이크포인트와 모바일 전환(→ `design/RESPONSIVE.md`)·컴포넌트 내부 구조(→ `design/COMPONENTS.md`). 읽는 시점: 새 페이지 골격을 잡거나 간격이 갈릴 때.

아직 레이아웃이 없다. **새 레이아웃이나 sticky 패턴을 신설한 그 턴 안에 여기 기록한다.**

## 정해야 할 것 (첫 레이아웃 작업 시)

- [ ] 앱 셸 구조 (사이드바 / 탑바 / 콘텐츠 그리드) — 데스크톱과 모바일 양쪽을 함께 정한다 (`design/RESPONSIVE.md`)
- [ ] sticky 헤더/필터 스펙 (`top` 값 계산 규칙)

> 반응형 브레이크포인트의 정본은 `design/RESPONSIVE.md`다. 브레이크포인트는 768px 하나뿐이다.

## 레이아웃 원칙 (impeccable 기반)

- **간격에 리듬을 준다** — 모든 간격이 같으면 위계가 사라진다. 관련 요소는 가깝게, 섹션 사이는 넓게 둔다.
- **Flexbox = 1D, Grid = 2D** — Grid가 기본값이 아니다. `flex-wrap`으로 충분하면 Flexbox를 쓴다.
- **반응형 그리드 (브레이크포인트 없이)**: `repeat(auto-fit, minmax(280px, 1fr))`.
- **z-index 시맨틱 스케일**: dropdown → sticky → modal-backdrop → modal → toast → tooltip. 임의값(999, 9999) 금지.
- **카드는 손쉬운 기본 답일 뿐이다** — 카드가 정말 가장 알맞은 어포던스일 때만 쓴다. 카드 안에 카드를 넣는 배치는 항상 틀렸다.
- **오버플로 체크**: `position: absolute` 드롭다운이 `overflow: hidden/auto` 컨테이너 안에 있으면 잘린다. 이때는 `<dialog>`, popover API, `position: fixed`, portal 중 하나를 쓴다.

## 규칙 (확정분)

- (첫 패턴 확정 시 기록)
