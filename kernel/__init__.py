"""하네스 커널 — 프로젝트와 무관한 판정 로직과 훅.

KERNEL_VERSION 은 배포된 커널의 버전이다. clone 해 간 프로젝트가 `harness_install.py --check-update` 로
원본 레포(UPSTREAM)의 같은 상수와 비교하고, `--upgrade` 는 커널·훅·프리셋만 교체한다. PROFILE_SCHEMA 는
커널이 요구하는 프로파일 서식의 버전이다. 프로파일에 선언된 버전이 이보다 낮으면 세션 시작 훅이 새로 생긴 항목을 알려준다.
"""

KERNEL_VERSION = "2.0.0"
PROFILE_SCHEMA = 1
UPSTREAM = "https://github.com/Gruci/agent-harness"
UPSTREAM_BRANCH = "master"
