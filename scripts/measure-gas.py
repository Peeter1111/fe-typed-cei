#!/usr/bin/env python3
"""Measure withdrawal gas for typed CEI and the persistent storage guard."""

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
    ]
    run = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if run.returncode != 0:
        sys.stdout.write(run.stdout)
        return run.returncode

    samples: dict[int, int] = {}
    for match in re.finditer(r"data: 0x([0-9a-fA-F]{128})", run.stdout):
        payload = match.group(1)
        kind = int(payload[:64], 16)
        gas = int(payload[64:], 16)
        samples[kind] = gas

    if set(samples) != {1, 2}:
        sys.stderr.write("expected gas samples for kinds 1 and 2\n")
        sys.stderr.write(run.stdout)
        return 1

    typed = samples[1]
    guarded = samples[2]
    overhead = guarded - typed
    percent = overhead * 100 / typed
    print(f"typed_cei_withdraw={typed}")
    print(f"storage_guard_withdraw={guarded}")
    print(f"storage_guard_overhead={overhead}")
    print(f"storage_guard_overhead_percent={percent:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
