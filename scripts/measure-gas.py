#!/usr/bin/env python3
"""Compare four withdrawals and their EIP-3529 refunds in this test transaction."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FE = os.environ.get("FE_BIN", "fe")
SSTORE_ZERO_RESET_REFUND = 19_900
REFUNDS = {
    1: SSTORE_ZERO_RESET_REFUND,
    2: 2 * SSTORE_ZERO_RESET_REFUND,
    3: SSTORE_ZERO_RESET_REFUND,
    4: SSTORE_ZERO_RESET_REFUND,
}


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

    samples: dict[int, tuple[int, int]] = {}
    matches = list(re.finditer(r"data: 0x([0-9a-fA-F]{192})", run.stdout))
    if len(matches) != 4:
        sys.stderr.write(f"expected exactly 4 gas sample events, got {len(matches)}\n")
        sys.stderr.write(run.stdout)
        return 1

    for match in matches:
        payload = match.group(1)
        kind = int(payload[:64], 16)
        gas = int(payload[64:128], 16)
        run_gas = int(payload[128:], 16)
        if kind in samples:
            sys.stderr.write(f"duplicate gas sample kind {kind}\n")
            sys.stderr.write(run.stdout)
            return 1
        samples[kind] = (gas, run_gas)

    if set(samples) != set(REFUNDS):
        sys.stderr.write("expected gas samples for kinds 1 through 4\n")
        sys.stderr.write(run.stdout)
        return 1

    # Each test creates, deposits and withdraws in ONE EVM transaction.
    # The ledger slot starts at zero, is set on deposit and reset on
    # withdrawal. The persistent lock is also set and reset in that tx.
    # EIP-2200/EIP-3529 credit 20,000 - 100 = 19,900 per zero reset.
    # The 20% transaction-level refund cap is demonstrably nonbinding if
    # even the measured create+deposit+withdraw gas exceeds 5 * refunds.
    for kind, (gross, run_gas) in samples.items():
        if run_gas < 5 * REFUNDS[kind]:
            sys.stderr.write(f"kind {kind}: refund cap cannot be excluded\n")
            return 1
        if gross < REFUNDS[kind]:
            sys.stderr.write(f"kind {kind}: refund exceeds gross delta\n")
            return 1

    typed = samples[1][0]
    guarded = samples[2][0]
    manual = samples[3][0]
    transient = samples[4][0]
    typed_overhead = typed - manual
    typed_percent = typed_overhead * 100 / manual
    guard_overhead = guarded - manual
    guard_percent = guard_overhead * 100 / manual
    guard_vs_typed = guarded - typed
    nets = {kind: gross - REFUNDS[kind] for kind, (gross, _) in samples.items()}
    print(f"typed_cei_withdraw={typed}")
    print(f"manual_cei_withdraw={manual}")
    print(f"storage_guard_withdraw={guarded}")
    print(f"transient_guard_withdraw={transient}")
    print(f"typed_vs_manual_overhead={typed_overhead}")
    print(f"typed_vs_manual_overhead_percent={typed_percent:.2f}")
    print(f"storage_guard_vs_manual_overhead={guard_overhead}")
    print(f"storage_guard_vs_manual_overhead_percent={guard_percent:.2f}")
    print(f"storage_guard_vs_typed_delta={guard_vs_typed}")
    print("refund_basis=same_transaction_create_deposit_withdraw")
    print("refund_cap=nonbinding_20_percent_verified_from_run_gas")
    for kind, label in (
        (1, "typed_cei"),
        (3, "manual_cei"),
        (2, "storage_guard"),
        (4, "transient_guard"),
    ):
        print(f"{label}_refund={REFUNDS[kind]}")
        print(f"{label}_net={nets[kind]}")
        print(f"{label}_run_gas_lower_bound={samples[kind][1]}")
    print(f"typed_net_vs_manual={nets[1] - nets[3]}")
    print(f"storage_guard_net_vs_manual={nets[2] - nets[3]}")
    print(f"transient_guard_net_vs_manual={nets[4] - nets[3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
