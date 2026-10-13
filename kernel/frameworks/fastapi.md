# kernel/frameworks/fastapi.md — FastAPI 서버 관례 조각

> 담는 것: FastAPI 서버팩을 고른 프로젝트의 스택 관례. 담지 않는 것: 스택 무관 서버 원칙(→ `dev/CONVENTIONS.md` 「공통 설계」·`dev/ARCHITECTURE.md`)·게이트 선언(→ `kernel/frameworks/fastapi.py`). 읽는 시점: 직접 읽지 않는다. 초기 설정의 스택 맞춤이 `dev/CONVENTIONS.md` 「스택 관례」 절에 넣는다.

### FastAPI 서버 관례

| # | 주제 | 정본 | 근거·예외 |
|---|------|------|-----------|
| FS1 | 라우트 선언 | `APIRouter` 에 `@router.get("/경로")` 꼴 데코레이터로 선언하고 앱에 include 한다. 팩의 `ROUTE_PATTERN` 이 이 모양을 읽는다 | 검사 31(소비 UI 없는 라우트)이 이 선언을 대상으로 잡는다 |
| FS2 | async 핸들러 | 실제 `await` 가 있을 때만 `async def` 로 쓴다. 스트림 응답(`StreamingResponse`)은 await 없이도 정상이다 | 검사 13 |
| FS3 | 에러 응답 | 에러는 `HTTPException` 으로 올린다. 응답 래퍼에 `status_code=` 로 4xx·5xx 를 실어 반환하지 않는다. 래퍼 이름은 프로파일 `SYMBOLS["error_response"]` 에 등록한다 | 검사 16 |
| FS4 | 커넥션 스코프 | DB 커넥션은 `with` 블록 안에서만 열고 fetch 한다. 업무 계산은 블록 밖에서 한다 | 「공통 설계」 커넥션 수명 행의 FastAPI 표현이다 |
| FS5 | 라우트 코드 | 라우트 함수에서 SQL 을 직접 쓰지 않는다. 승인된 포트·어댑터 컴포넌트를 거친다 | |
