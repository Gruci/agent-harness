"""kernel/gates/schema.py — DDL 저장 타입 잘림 금지 (래칫).

금액 컬럼을 REAL(float4)로 선언하면 원 단위 값이 유효 8자리에서 잘려 저장된다. 화면·다운로드·
파생 계산이 전부 잘린 값을 쓰는데 예외는 나지 않는다 — 조용히 틀린다. 실제로 20개 컬럼이
이 상태로 운영되다 발견된 적이 있고, 그 감사가 이 게이트를 만들었다.

⑭A REAL/FLOAT4/FLOAT(n<=24) 선언 금지 — float4 는 2^24(16,777,216) 초과 정수를 표현하지 못한다.
    비율·점수라도 DOUBLE PRECISION 을 쓴다. 4바이트를 아껴서 얻는 것이 없고, "이건 비율이니 REAL
    이어도 된다"는 판단을 매번 해야 한다는 것 자체가 실수가 새어 드는 틈이다.
⑭B NUMERIC(p,s) 의 s>0 은 같은 줄에 소스 정밀도 근거 주석 필수 — 스케일은 소스를 실제로 본
    사람만 정할 수 있다. `# any-ok: 사유` 와 같은 방식이며, 강제하려는 것은 주석 문구가 아니라 소스를 확인하는 행위다.

기존 선언은 ddl_types_baseline.txt 에 `경로:컬럼명` 으로 동결 — 줄어들기만 해야 한다.
줄 번호가 아니라 컬럼명을 키로 쓰는 이유는 줄 번호가 무관한 편집에도 밀리기 때문이다.
"""

from __future__ import annotations

import re
from pathlib import Path

from kernel import profile
from kernel.context import READ_ENC, ROOT, _rel, read_list

BASELINE_FILE = ROOT / "ddl_types_baseline.txt"

# `"합계" REAL` · `shares_short REAL` · `x FLOAT(24)` — 한 줄에 여러 컬럼이 오므로 finditer.
LOSSY_FLOAT = re.compile(
    r'"?([\w가-힣]+)"?\s+(REAL|FLOAT4|FLOAT\s*\(\s*(?:[1-9]|1[0-9]|2[0-4])\s*\))(?=[\s,)])',
    re.IGNORECASE,
)
SCALED_NUMERIC = re.compile(r'"?([\w가-힣]+)"?\s+NUMERIC\s*\(\s*\d+\s*,\s*[1-9]', re.IGNORECASE)


def check_ddl_lossy_types(py_files: list[Path]) -> list[str]:
    """게이트 ⑭: DDL 에서 소스 정밀도를 담지 못하는 타입 선언 검출."""
    target = profile.layer_raw("schema")
    if not target:
        return []
    baseline = read_list(BASELINE_FILE)
    bad: list[str] = []
    for f in py_files:
        rel = _rel(f)
        if not rel.startswith(target):
            continue
        for i, line in enumerate(f.read_text(encoding=READ_ENC).splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for m in LOSSY_FLOAT.finditer(line):
                if f"{rel}:{m.group(1)}" in baseline:
                    continue
                bad.append(
                    f"{rel}:{i}: {m.group(1)} {m.group(2)} — DOUBLE PRECISION(실수)·"
                    f"BIGINT(정수)·NUMERIC(고정소수) 중 하나로. float4 는 2^24 초과 정수를 못 담는다"
                )
            if "--" in line or "#" in line:   # 같은 줄에 소스 정밀도 근거가 있으면 통과
                continue
            for m in SCALED_NUMERIC.finditer(line):
                if f"{rel}:{m.group(1)}" in baseline:
                    continue
                bad.append(
                    f"{rel}:{i}: {m.group(1)} NUMERIC 소수 스케일에 소스 정밀도 근거 주석 없음 — "
                    f"같은 줄에 `-- <소스> 소수 N자리` 를 달 것 (스케일은 소스를 본 사람만 정한다)"
                )
    return bad
