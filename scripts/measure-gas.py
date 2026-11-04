#!/usr/bin/env python3
"""Measure raw withdrawal gas for manual CEI, typed CEI, and a storage guard."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FE = os.environ.get("FE_BIN", "fe")


def main() -> int:
    command = [
        FE,
        "test",
        "--color",
        "never",
        "-O",
        "2",
        "--filter",
        "gas_",
        "--show-logs",
        str(ROOT / "test_harness"),
    ]
    run = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if run.returncode != 0:
        sys.stdout.write(run.stdout)
        return run.returncode

    samples: dict[int, int] = {}
    matches = list(re.finditer(r"data: 0x([0-9a-fA-F]{128})", run.stdout))
    if len(matches) != 3:
        sys.stderr.write(f"expected exactly 3 gas sample events, got {len(matches)}\n")
        sys.stderr.write(run.stdout)
        return 1

    for match in matches:
        payload = match.group(1)
        kind = int(payload[:64], 16)
        gas = int(payload[64:], 16)
        if kind in samples:
            sys.stderr.write(f"duplicate gas sample kind {kind}\n")
            sys.stderr.write(run.stdout)
            return 1
        samples[kind] = gas

    if set(samples) != {1, 2, 3}:
        sys.stderr.write("expected gas samples for kinds 1, 2, and 3\n")
        sys.stderr.write(run.stdout)
        return 1

    typed = samples[1]
    guarded = samples[2]
    manual = samples[3]
    typed_overhead = typed - manual
    typed_percent = typed_overhead * 100 / manual
    guard_overhead = guarded - manual
    guard_percent = guard_overhead * 100 / manual
    guard_vs_typed = guarded - typed
    print(f"typed_cei_withdraw={typed}")
    print(f"manual_cei_withdraw={manual}")
    print(f"storage_guard_withdraw={guarded}")
    print(f"typed_vs_manual_overhead={typed_overhead}")
    print(f"typed_vs_manual_overhead_percent={typed_percent:.2f}")
    print(f"storage_guard_vs_manual_overhead={guard_overhead}")
    print(f"storage_guard_vs_manual_overhead_percent={guard_percent:.2f}")
    print(f"storage_guard_vs_typed_delta={guard_vs_typed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
