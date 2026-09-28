"""Technical check scopes and root litter; component placement belongs to the graph."""

from __future__ import annotations
import subprocess
from kernel import profile
from kernel.context import ROOT


SELF_FILES = ("harness_profile.py", "harness_install.py")


ROOT_INFRA = frozenset({
    ".gitignore", "setup_global_permissions.py",
    "harness_baseline.txt", "harness_surface.txt", "harness_trace.jsonl",
    "harness_maintenance.json", "test_pairing_baseline.txt",
    "md_style_baseline.txt", "md_ref_allowlist.txt",
    "dup_decl_baseline.txt", "dup_block_baseline.txt", "api_array_baseline.txt",
})


def check_root_litter() -> list[str]:
    """루트 바로 아래에는 프로파일 ROOT_FILES 에 등재한 파일만 둔다. 확장자는 따지지 않는다.

    git 이 추적하지 않는 파일도 검사하므로, 로컬에만 두는 파일은 `.git/info/exclude` 로 제외한다.
    """
    allow = set(profile.ROOT_FILES) | set(SELF_FILES) | ROOT_INFRA
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True)
    names = {line.strip() for line in out.stdout.splitlines()}
    strays = sorted(n for n in names if n and "/" not in n
                    and n not in allow and (ROOT / n).exists())
    return [f"{n}: 루트 직속 파일 금지 — 읽는 코드의 패키지 안에 두고, 루트가 맞으면 사유와 "
            f"함께 프로파일 ROOT_FILES 에 등재하라" for n in strays]
