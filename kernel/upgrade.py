"""kernel/upgrade.py — 원류 이력 기반 업그레이드와 버전 확인.

  python -X utf8 harness_install.py --check-update          원류 기본 브랜치의 KERNEL_VERSION 만 읽어 알린다
  python -X utf8 harness_install.py --upgrade [--keep-local]  하네스 소유 파일을 원류 이력으로 판정해 맞춘다
  python -X utf8 -m kernel.upgrade [--keep-local]           같은 일. `kernel.upgrade` 가 없던 옛 업그레이더가 남아 있을 때의 진입점이다

clone 해 간 프로젝트는 원류와 git 연결이 끊겨 있다. 그래서 파일마다 **원류 git 이력** 으로 판정한다 — 매니페스트
파일은 지금 있는 설치에 없고, 이력은 모든 설치에 같은 판정을 준다.

  same     원류 최신과 같다
  replace  원류 이력에 있던 내용이다 — 원류가 고친 것을 받는다
  delete   원류 최신에 없고, 이 파일은 이력에 있던 그대로다 — 원류가 지운 것을 따른다
  add      이 프로젝트에 없던 원류 파일
  local    원류 이력에 없는 내용이다 — 이 프로젝트가 고쳤다. 하나라도 있으면 아무것도 바꾸지 않고 멈춘다
  project  원류 이력에 없던 경로 — 이 프로젝트의 파일. 건드리지 않는다

로컬 수정을 덮고 백업만 두면 원류로 돌아갈 신호가 사라진다. 멈추고 원류 이슈 초안을 내는 것이 자란 것이 원류로 가는 길이다.
`.claude/settings.json` 은 프로젝트 소유라 바꾸지 않는다. 원류와 다른 훅 배선은 `kernel/harness_setup.py` 가 알리기만 한다.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from kernel import KERNEL_VERSION, UPSTREAM, UPSTREAM_BRANCH
from kernel.context import ROOT

OWNED = ("kernel/", ".claude/hooks/", "profiles/", "harness_install.py", "setup_global_permissions.py")
KINDS = ("add", "replace", "delete", "same", "local", "project")
_VERSION_RE = re.compile(r'^KERNEL_VERSION\s*=\s*"([^"]+)"', re.M)
_RAW_ENTRY = re.compile(r"^:\d+ \d+ ([0-9a-f]+) ([0-9a-f]+) ")
_NO_BLOB = "0" * 40
# 공개 이력을 새로 시작하기 전에 배포된 판의 지문. 그 전에 설치한 프로젝트도 손대지 않은 파일이 원본으로 읽힌다.
RELEASED_BLOBS = "kernel/released_blobs.txt"


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".") if part.isdigit())


def upstream_version() -> str:
    """원류 기본 브랜치의 KERNEL_VERSION 을 돌려준다. 파일 하나만 내려받고, clone 은 --upgrade 때만 한다."""
    raw = UPSTREAM.replace("https://github.com/", "https://raw.githubusercontent.com/")
    # 캐시를 우회한다 — raw CDN 이 몇 분 전 버전을 돌려주면 최신이라고 잘못 판단한다
    url = f"{raw}/{UPSTREAM_BRANCH}/kernel/__init__.py?t={int(time.time())}"
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read().decode("utf-8", "replace")
    found = _VERSION_RE.search(body)
    return found.group(1) if found else ""


def check_update() -> int:
    try:
        latest = upstream_version()
    except Exception as exc:                                  # 네트워크 오류·404 — 알리기만 하고 끝낸다
        print(f"[UPDATE] Could not check upstream — {exc.__class__.__name__}: {exc}")
        return 2
    if not latest:
        print("[UPDATE] Could not read KERNEL_VERSION upstream — upstream predates the version constant")
        return 2
    if _version_tuple(latest) > _version_tuple(KERNEL_VERSION):
        print(f"[UPDATE] Harness {KERNEL_VERSION} → {latest} available.")
        print(f"   python -X utf8 harness_install.py --upgrade judges every harness-owned file ({' '.join(OWNED)}) by upstream history.")
        print("   A file this project changed stops the upgrade. harness_profile.py · source-of-truth MDs · harness_gates/ · docs/ are never touched.")
        return 1
    print(f"[UPDATE] Up to date ({KERNEL_VERSION}).")
    return 0


def blob_id(path: Path) -> str:
    """git blob id. 줄 끝을 LF 로 맞춰 Windows 체크아웃의 CRLF 사본도 원류 blob 과 같게 센다."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def owned_files(root: Path) -> dict[str, Path]:
    """하네스 소유 경로 아래 실제 파일(경로 → 실물). `__pycache__` 는 어느 쪽 소유도 아니다."""
    found: dict[str, Path] = {}
    for owned in OWNED:
        target = root / owned
        if target.is_file():
            found[owned] = target
        elif target.is_dir():
            found.update({path.relative_to(root).as_posix(): path for path in target.rglob("*")
                          if path.is_file() and "__pycache__" not in path.parts})
    return found


def history(checkout: Path) -> dict[str, set[str]]:
    """원류 체크아웃의 이력에서 경로마다 가졌던 blob 전부. 지운 파일의 마지막 내용과 이력 재시작 전 배포분도 들어 있다."""
    done = subprocess.run(["git", "log", "--format=", "--raw", "-z", "-m", "--no-abbrev", "--no-renames", "--",
                           *(owned.rstrip("/") for owned in OWNED)],
                          cwd=checkout, capture_output=True, check=True)
    seen: dict[str, set[str]] = {}
    tokens = done.stdout.decode("utf-8", "replace").split("\0")
    for index in range(len(tokens) - 1):
        entry = _RAW_ENTRY.match(tokens[index].lstrip("\n"))
        if entry:
            blobs = {blob for blob in entry.groups() if blob != _NO_BLOB}
            seen.setdefault(tokens[index + 1], set()).update(blobs)
    released = checkout / RELEASED_BLOBS
    lines = released.read_text(encoding="utf-8").splitlines() if released.is_file() else []
    for rel, _tab, blob in (line.partition("\t") for line in lines if not line.startswith("#")):
        if blob:
            seen.setdefault(rel, set()).add(blob)
    return seen


def classify(project: Path, checkout: Path) -> dict[str, list[str]]:
    """경로마다 add·replace·delete·same·local·project 중 하나. local 은 이 프로젝트가 고친 파일이다."""
    seen, new, old = history(checkout), owned_files(checkout), owned_files(project)
    plan: dict[str, list[str]] = {kind: [] for kind in KINDS}
    for rel in sorted(set(new) | set(old)):
        if rel not in old:
            kind = "add"
        elif rel in new:
            mine = blob_id(old[rel])
            kind = "same" if mine == blob_id(new[rel]) else "replace" if mine in seen.get(rel, ()) else "local"
        elif rel in seen:
            kind = "delete" if blob_id(old[rel]) in seen[rel] else "local"
        else:
            kind = "project"
        plan[kind].append(rel)
    return plan


def issue_draft(local: list[str]) -> str:
    """로컬 수정을 원류로 돌려보내는 이슈 초안. 멈춤이 곧 환류의 시작점이다."""
    files = " ".join(local)
    return ("\n".join([
        "[UPGRADE] Stopped — this project changed harness-owned files, and an upgrade would overwrite that work:",
        *(f"   {rel}" for rel in local),
        "   Send the change upstream so the next version carries it, then upgrade:",
        f'   gh issue create --repo {UPSTREAM.removeprefix("https://github.com/")} '
        f'--title "Local harness fix: {files}" --body "$(git log -1 --format=%s -- {files})"',
        "   Or keep the local versions and upgrade everything else: python -X utf8 harness_install.py --upgrade --keep-local",
    ]))


def _apply(project: Path, checkout: Path, plan: dict[str, list[str]]) -> None:
    for rel in plan["add"] + plan["replace"]:
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(checkout / rel, target)
    for rel in plan["delete"]:
        (project / rel).unlink()
    for kind in ("add", "replace", "delete", "local"):
        if plan[kind]:
            print(f"[UPGRADE] {kind} {len(plan[kind])}: {' '.join(plan[kind])}")
    print(f"[UPGRADE] same {len(plan['same'])} · project-owned {len(plan['project'])} (untouched)")


def _diagnose(root: Path) -> int:
    """새 프로세스에서 교체된 커널의 진단을 돌린다. 현재 프로세스는 이전 모듈을 캐시하고 있다."""
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "kernel.harness_setup"], cwd=root).returncode


def run(argv: list[str]) -> int:
    """하네스가 소유한 파일을 원류 이력으로 판정해 맞춘다. 되돌리기는 git 에 맡기므로 작업 트리가 깨끗해야 시작한다."""
    keep_local = "--keep-local" in argv
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8").stdout.strip()
    if dirty:
        print("[UPGRADE] The working tree is not clean — commit or revert, then run again. The replacement must be revertible with git.")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        checkout = Path(tmp) / "upstream"
        done = subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--branch", UPSTREAM_BRANCH,
                               UPSTREAM, str(checkout)], capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            print(f"[UPGRADE] Upstream clone failed — {done.stderr.strip()[:300]}")
            return 2
        found = _VERSION_RE.search((checkout / "kernel" / "__init__.py").read_text(encoding="utf-8"))
        latest = found.group(1) if found else "?"
        plan = classify(ROOT, checkout)
        if plan["local"] and not keep_local:
            print(issue_draft(plan["local"]))
            return 2
        _apply(ROOT, checkout, plan)
        from kernel import harness_setup
        for line in harness_setup.wiring_diff(ROOT, checkout):
            print(line)
    print(f"\n[UPGRADE] {KERNEL_VERSION} → {latest}. Next:")
    print("   python -X utf8 -m kernel.profile     check new profile entries")
    print("   python -X utf8 -m kernel.runner      re-verify every gate")
    print("   Review the changes with git diff. Merge only the settings, skills and shared workflows you need.")
    return _diagnose(ROOT)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
