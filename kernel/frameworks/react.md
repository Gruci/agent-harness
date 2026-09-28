# kernel/frameworks/react.md — React 화면 관례 조각

> 담는 것: React(TSX) 화면팩을 고른 프로젝트의 스택 관례. 담지 않는 것: 스택 무관 화면 원칙(→ `dev/CONVENTIONS.md` 「화면 관례」)·게이트 선언(→ `kernel/frameworks/react.py`). 읽는 시점: 직접 읽지 않는다. 초기 설정의 스택 맞춤이 `dev/CONVENTIONS.md` 「스택 관례」 절에 넣는다.

### React 화면 관례

| # | 주제 | 정본 | 근거·예외 |
|---|------|------|-----------|
| RF1 | 데이터 fetch | `useApi`(TanStack Query 래퍼) 하나만 쓴다. 프로파일 `ALLOWLIST["ui_fetch_wrappers"]` 에 이 훅을 등록한다 | 첫 구현 시 useApi 훅부터 만든다 |
| RF2 | 디자인 토큰 | `constants/` 의 TS 상수가 정본이고 CSS `:root` 변수는 상수에서 파생한다(동기 유지). 프로파일 `CHECK_PATHS["ui_tokens"]` 가 그 파일을 가리킨다 | 토큰 값은 네이티브 포팅 때 StyleSheet 에서 그대로 재사용 |
| RF3 | 차트 래퍼 | `charts/` 에 타입별 래퍼(Line/Bar/Doughnut)를 두고 래퍼가 `CHART_DEFAULTS` 를 넣는다. 원본 프로젝트의 조합은 Chart.js + react-chartjs-2 | |
| RF4 | 컴포넌트 배치 | 한 페이지 전용은 `components/<page>/`, 두 페이지 이상이 쓰면 `components/common/` | |
| RF5 | 수치 표시 | `utils/` 의 공용 포맷 모듈 함수로 표시한다 | |
| RF6 | 화면/로직 분리 | `.tsx` 는 표시(JSX)만 맡는다. 데이터 가공·계산·조건 분기는 `hooks/`·`utils/` 의 순수 TS 함수로 뺀다 | 네이티브 전환 때 hooks·utils 는 그대로 옮기고 화면만 다시 쓴다 |
| RF7 | 라우팅 접점 | 라우터(react-router 등) import 와 페이지 이동 호출은 `pages/` 에서만 한다. 하위 컴포넌트에는 콜백 prop 으로 전달한다 | 라우터는 네이티브 전환 때 통째로 바뀐다. 접점이 적을수록 비용이 적다 |
| RF8 | 브라우저 API | `window.`·`document.`·`localStorage` 는 플랫폼 래퍼를 거친다. 래퍼는 `ALLOWLIST["ui_platform"]` 에 등록하고, 불가피하면 `// web-ok: 사유` | 검사 20. 네이티브에는 브라우저 API 가 없다 |

### 네이티브 앱(React Native) 포팅 대비

RF2·RF6·RF7·RF8 은 나중에 React Native 앱으로 옮길 때 화면층만 다시 쓰면 되도록 로직과 토큰을 화면에서 분리해 두는 규칙이다.
그대로 옮겨 쓰는 것은 TS 순수 로직(hooks/·utils/), 디자인 토큰 값, API 레이어다. 다시 쓰는 것은 HTML/CSS, 브라우저 API, 라우터다.
