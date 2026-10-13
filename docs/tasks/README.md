# docs/tasks/ — 과업 설계 문서

> 담는 것: 이 폴더에 무엇이 언제 생기고 어디로 가는지. 담지 않는 것: 4단계 절차(→ `dev/workflows/feature-workflow.md`)·보드 서식(→ `workboard/README.md`). 읽는 시점: 과업 문서를 처음 만들 때.

기능 작업의 1~2단계 산출물인 `docs/tasks/research_<과업>.md` 와 `docs/tasks/plan_<과업>.md` 가 여기 생긴다.
구현 전이라 worktree 가 없으므로 본체 체크아웃에서 쓴다. 이 폴더는 편집 가드의 예외다.

| 시점 | 일어나는 일 |
|---|---|
| 리서치 시작 | `kernel.task plan` 이 과업을 보드에 올리고, 두 문서를 여기 쓴다 |
| 구현 중 | plan 은 과업이 끝날 때까지 여기 있다 |
| 끝내기 | `kernel.task finish` 가 두 문서를 `archive/` 아래 그 과업 폴더로 옮긴다 |

`wip_` 접두는 보드 밖에서 세션을 넘겨 이어지는 문서의 표시다. 끝난 과업의 문서가 루트에 남아 있으면 종료 검사(⑰)가 막는다.
