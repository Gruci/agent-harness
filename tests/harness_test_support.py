"""Temporary project roots with unittest-managed cleanup, plus the shared workboard fixture."""

import tempfile
import unittest
from pathlib import Path


class TemporaryRootTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary_root = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_root.cleanup)
        self.root = Path(temporary_root.name)


# workboard 과업 파일 픽스처. 이 픽스처로 잡는 회귀: 파일 하나가 보드 행 하나라는 계약, 브랜치를 엉뚱한 필드에서 읽는 오류, 겹침 판정, 이름 조인.
TASK_TEXT = (
    "- 범위: admin-report-viewers\n"
    "- 과업: feat/report-viewers #sid:abcd1234\n"
    "- 손대는 곳:\n"
    "  - frontend/src/components/admin/salesStatus/*\n"
    "  - docs/tasks/plan_x.md\n"
    "- 상태: 진행\n"
)


def fake_board(base: Path) -> Path:
    """과업 파일 하나와 README 를 가진 보드. README 는 서식 설명이라 과업으로 세면 안 된다."""
    board = base / "workboard"
    board.mkdir()
    (board / "admin-report-viewers.md").write_text(TASK_TEXT, encoding="utf-8")
    (board / "README.md").write_text("# 서식\n- 과업: feat/example #sid:deadbeef\n",
                                     encoding="utf-8")
    return board
