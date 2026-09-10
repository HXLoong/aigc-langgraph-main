"""一键运行全部 20 个 GOATS 接口测试。
用法: python tests/api/run_all.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
FILES = sorted(
    f.name for f in HERE.glob("test_[0-9][0-9]_*.py")
)

print("=" * 60)
print(f"GOATS 全接口测试 ({len(FILES)} 个)")
print("=" * 60)

passed = 0
failed = 0

for name in FILES:
    r = subprocess.run(
        [sys.executable, str(HERE / name)],
        capture_output=True, text=True,
    )
    # 最后一行是结果
    lines = [line for line in r.stdout.strip().split("\n") if line.strip()]
    last = lines[-1] if lines else ""
    if "[OK]" in last:
        passed += 1
        status = "OK"
    elif "[FAIL" in last:
        failed += 1
        status = "FAIL"
    else:
        failed += 1
        status = "???"
    print(f"[{status}] {name}")

print(f"\n{f'通过 {passed}/{len(FILES)}' if not failed else f'通过 {passed}/{len(FILES)}  失败 {failed}'}")
