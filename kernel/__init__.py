"""하네스 커널 — 프로젝트와 무관한 판정 로직과 훅.

KERNEL_VERSION 은 배포된 커널의 버전이다. clone 해 간 프로젝트가 `harness_install.py --check-update` 로
원본 레포(UPSTREAM)의 같은 상수와 비교하고, `--upgrade` 는 하네스 소유 파일마다 원류 git 이력으로 판정해 맞춘다
(`kernel/upgrade.py` — 이 프로젝트가 고친 파일이 있으면 멈추고 원류 이슈 초안을 낸다). PROFILE_SCHEMA 는
커널이 요구하는 프로파일 서식의 버전이다. 프로파일에 선언된 버전이 이보다 낮으면 세션 시작 훅이 새로 생긴 항목을 알려준다.
"""

KERNEL_VERSION = "1.3.1"
PROFILE_SCHEMA = 1
UPSTREAM = "https://github.com/Gruci/dev-harness"
UPSTREAM_ALIASES = ("gruci/agent-harness",)
UPSTREAM_BRANCH = "master"
