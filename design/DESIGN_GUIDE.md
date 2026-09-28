# design/DESIGN_GUIDE.md — UI 디자인 허브

> 담는 것: UI 작업의 라우팅 허브와 디자인 5원칙. 담지 않는 것: 색상·컴포넌트·레이아웃·차트·UX의 상세(→ `design/` 서브MD)·백엔드 규칙(→ `dev/DEVGUIDE.md`). 읽는 시점: 화면 코드(프로파일 `CHECK_PATHS["ui"]`)를 만지기 전, 그리고 어느 `design/` MD를 읽을지 고를 때.
> 정본 값: 토큰 파일(프로파일 `CHECK_PATHS["ui_tokens"]`)과 CSS `:root` 변수다. 둘 다 첫 스캐폴딩 때 만든다.
> 이 MD에는 라우팅, 5대 원칙, 체크리스트만 둔다. 실제 스펙은 `design/` 서브MD에 있고, **패턴을 새로 만든 그 턴 안에 서브MD에 기록**한다.

---

## 라우팅 테이블

작업 시작 전 해당 MD를 on-demand로 Read한다.

| 작업 대상 | 읽어야 할 MD |
|-----------|-------------|
| 색상 변수·TS 상수·타이포·수치 포맷 | `design/COLORS.md` |
| 레이아웃·sticky 헤더·그리드 | `design/LAYOUT.md` |
| 카드·툴팁·탭·버튼·컴포넌트 | `design/COMPONENTS.md` |
| 차트 패턴·legend·tooltip | `design/CHARTS.md` |
| UX 동작·필터 원칙·레이블 | `design/UX.md` |
| **반응형·모바일 대응·브레이크포인트 (모든 화면 작업)** | `design/RESPONSIVE.md` |

---

## 5대 원칙 ★

1. **Hex 하드코딩 금지** — CSS에서는 `var(--...)`를 쓰고, 코드에서는 토큰 파일(`CHECK_PATHS["ui_tokens"]`)을 import한다. (게이트가 검사)
2. **색상 중앙화** — 한 번만 쓰면 로컬 const 허용, 두 페이지 이상이면 반드시 토큰 파일 / CSS `:root`에 올린다.
3. **차트 래퍼 통일** — 모든 차트는 화면 레이어의 차트 래퍼 모듈을 거쳐 만들고, 래퍼가 기본 옵션을 자동으로 넣는다. 라이브러리로 직접 생성하지 않는다. 래퍼 위치는 `dev/CONVENTIONS.md` 「스택 관례」가 정한다.
4. **수치 포맷 중앙화** — 금액과 수치는 공용 포맷 모듈의 함수로 표시한다. 모듈은 첫 구현 때 만들고 위치를 `dev/CONVENTIONS.md` 공용 헬퍼 표에 등재한다. 페이지마다 따로 구현하지 않는다.
5. **웹+모바일 동등 설계** — 모든 화면은 plan 단계에서 데스크톱 배치와 모바일 배치를 함께 정한다 (`design/RESPONSIVE.md`). 구현을 마친 뒤에 모바일을 따로 맞추지 않는다.

---

## 커밋 전 체크리스트

- [ ] 금액·수치 요소에 `white-space: nowrap` 있는가?
- [ ] `text-overflow: ellipsis` 없는가? (수치 잘림 금지)
- [ ] 표시 포맷은 공용 포맷 모듈 경유인가?
- [ ] 차트는 래퍼 경유인가?
- [ ] 숫자·차트·표 각 패널에 출처/기준/계산식 주석(Footnote)이 있는가?
- [ ] 새 색상을 임의로 추가하지 않았는가?
- [ ] 레이블이 자기설명적인가? (조어·내부용어 금지 — `design/UX.md`)
- [ ] 모바일(390px)에서 가로 스크롤 없는가? 터치 타깃 44px 확보했는가? (`design/RESPONSIVE.md`)

> 프로젝트 고유 체크 항목(색 의미론·강조색 등)은 확정되는 대로 여기에 추가한다.

---

## impeccable 디자인 스킬 연동

UI 디자인·리뷰·개선 작업 시 `/impeccable` 스킬을 활용한다. UI 파일을 편집하면 이 스킬의 자동 훅(PostToolUse)이 그 자리에서 디자인 품질을 검사한다.

| 명령 | 용도 |
|------|------|
| `/impeccable craft [기능]` | 새 UI 기능 설계→구현 |
| `/impeccable critique [대상]` | UX 휴리스틱 점수 리뷰 |
| `/impeccable audit [대상]` | 기술 품질(a11y, 성능, 반응형) |
| `/impeccable polish [대상]` | 출하 전 최종 품질 패스 |
| `/impeccable animate [대상]` | 모션 추가 |
| `/impeccable colorize [대상]` | 색 전략 적용 |
| `/impeccable typeset [대상]` | 타이포그래피 개선 |
| `/impeccable layout [대상]` | 간격·리듬·위계 수정 |

> 전체 명령 목록은 `.claude/skills/impeccable/SKILL.md` 참조.
