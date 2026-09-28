"""Claude PreToolUse adapter — 편집 가드·worktree 이름·나올 때 검사를 kernel.hook 에 위임한다.

매처는 `Edit|Write|MultiEdit|NotebookEdit|EnterWorktree|Bash|PowerShell` 다. 셸 툴을 전부 담아야
같은 명령이 PowerShell 로 빠져나가지 않는다. 판정은 `kernel/isolation.py`·`kernel/worktree.py` 이고
Codex 도 같은 진입점을 부른다. 커널이 차단으로 판정하면 `sys.exit(2)`, 판정하지 못하면 exit 1 이다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kernel.hook import main


if __name__ == "__main__":
    sys.exit(main(["--agent", "claude", "--event", "PreToolUse"]))
