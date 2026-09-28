"""kernel/langs/python.py — 파이썬 언어팩. 관용구 패턴은 다른 팩의 기본값이기도 하다(`kernel/lang.py` DEFAULTS).

커널이 파이썬으로 돌기 때문에 `ast` 를 그냥 쓸 수 있다(`kernel/analyzers/python.py`). 그래서
구문 사실 게이트가 전부 켜지고, 해당 없음으로 빠지는 것도 없다. 다른 언어팩의 기준선 역할을
한다 — QUERIES 가 없는 것은 결함이 아니라 표준 ast 가 그 자리를 맡기 때문이다.
"""

from __future__ import annotations

EXT = ("*.py",)
SYNTAX = "python"

# 적합성 검사 예제. 기준선 팩이라 pack_check 가 [1급] 판정 경로 자체를 여기로 증명한다.
FIXTURES = {
    "closures": {
        "violating": "def outer():\n    def inner():\n        return 1\n    return inner()\n",
        "passing": "def flat():\n    return 1\n",
    },
    "func_limit": {
        "violating": "def long_calc():\n" + "    x = 1\n" * 80 + "    return x\n",
        "passing": "def short() -> int:\n    return 1\n",
    },
    "type_hints": {
        "violating": "def place(order):\n    return order\n",
        "passing": "def place(order: int) -> int:\n    return order\n",
    },
    "imports": {"source": "from db.reads import board\nimport os\n", "expect": ["db.reads"]},
    "top_symbols": {"source": "def f():\n    pass\n\nclass C:\n    pass\n\nX = 1\n", "expect": ["f", "C", "X"]},
}

PATTERNS = {
    "env_read":    r"\bos\.(getenv|environ)\b",
    "any_type":    r"[:\[,]\s*Any\b|->\s*Any\b",
    "any_escape":  "any-ok",
    "closure_escape": "closure-ok",
    "comment":     "#",
    "import_stmt": r"\bimport\b",
}

NOT_APPLICABLE: dict[str, str] = {}

LINTERS = [
    {"slug": "ruff", "cmd": ["ruff", "check", "--output-format=concise", "."],
     "parse": "gcc", "install": "pip install ruff"},
]
