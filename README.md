# typed-cei

**Move one checks-effects-interactions boundary from a review convention into a compiler-checked API. The ledger debits before calls, and payout dispatch has `Ctx + Call` authority but no `Ledger` authority.**

`typed-cei` is a small Fe 26.5 library with ETH and ERC20 vaults and an auction-refund example. It does not make arbitrary Fe code reentrancy-safe. Callers cannot forge a payout, dispatch the same payout twice, or widen an asset adapter's dispatch effects to include the ledger. A one-call withdrawal keeps a simple payout inside the library until dispatch.

```text
withdraw_and_dispatch(...) → debit → send, all inside one call

commit_withdraw(...)       → Payout<Native> → dispatch()
                               private fields   consumes value
```

The repository includes a deliberately vulnerable vault, hand-written CEI, persistent and transient reentrancy guards, a callback attacker, exact compile-fail diagnostics, and a reproducible gas comparison.

## Why this exists

Fe already catches an important class of reentrancy hazards. Its access checker rejects an external call while a conflicting storage access is still open:

```fe
let held = mut balance
call.send_value(addr: to, gas: 100000, value: Wei::zero()) // compile error
held = 0
```

But this classic bad order is legal because the storage read has ended before the call:

```fe
let amount = balances[owner]
call.send_value(addr: to, gas: ctx.gas(), value: wei(amount))
balances[owner] = 0
```

`VulnerableVault` does exactly that, compiles on Fe 26.5.0, and is drained by the runtime attacker in this repository.

The library adds a second boundary after Fe's built-in access checking. Its trusted accounting module owns the `Payout` constructor. Public commit functions debit storage before returning a payout. Code outside the module can hold and consume it, but cannot construct one directly. Simple withdrawals use a single library function that commits and dispatches without returning a capability.

## The core pattern

The payout fields and constructor are private:

```fe
#[must_use]
pub struct Payout<A> {
    asset: A,
    to: Address,
    amount: u256,
}

pub fn commit_withdraw<A: Asset>(owner: Address, to: Address, asset: own A) -> Payout<A>
uses (ledger: mut Ledger)
{
    let amount = ledger.balances[owner]
    assert!(amount > 0, "nothing to withdraw")
    ledger.balances[owner] = 0
    Payout::new(asset, to, amount)
}
```

Dispatch consumes the capability. The `Asset` trait fixes its effect row to external-call authority only:

```fe
pub trait Asset {
    fn send(own self, to: Address, amount: u256) uses (ctx: Ctx, call: mut Call)
}

impl<A: Asset> Payout<A> {
    pub fn dispatch(own self) uses (ctx: Ctx, call: mut Call) {
        self.asset.send(to: self.to, amount: self.amount)
    }
}
```

This fixed trait signature is important. Third-party asset adapters are allowed, but Fe rejects an implementation that adds `mut Ledger` (or any other extra effect) as having stricter bounds than the trait.

Two adapters are included: `Native` sends wei with `Call::send_value`; `Erc20Asset` uses `std::evm::erc20::safe_transfer`.

The default single-payout path does not return a discardable value:

```fe
pub fn withdraw_and_dispatch<A: Asset>(owner: Address, to: Address, asset: own A) -> u256
uses (ledger: mut Ledger, ctx: Ctx, call: mut Call)
{
    let payout = commit_withdraw(owner, to, asset)
    let amount = payout.amount()
    payout.dispatch()
    amount
}
```

The debit and external call execute in one transaction. A failed transfer reverts the debit. `Payout` remains public for splits and batches.

## Worked vault

`TypedVault` supports payable `deposit()`, `withdraw(address)`, `withdrawSplit(address,address,uint256)`, and `balanceOf(address)`.

The normal withdrawal is one library call:

```fe
withdraw_and_dispatch(owner: ctx.caller(), to, asset: native())
```

`commit_split` shows composition: one committed debit can return two independently consumable payouts, then both interactions happen after the ledger write.

## ERC20 deposit and payout

`TokenVault` requires an ERC20 allowance and calls `safe_transfer_from`. It reads `balanceOf(vault)` before and after the call, then credits the positive difference. It never credits the amount requested without checking receipt.

```fe
let before: u256 = call.call(
    addr: token, gas: ctx.gas(), value: Wei::zero(),
    message: TokenBalanceQuery::BalanceOf { owner: ctx.address() },
)
erc20::safe_transfer_from(token: token, owner: ctx.caller(), receiver: ctx.address(), amount)
let after: u256 = call.call(
    addr: token, gas: ctx.gas(), value: Wei::zero(),
    message: TokenBalanceQuery::BalanceOf { owner: ctx.address() },
)
assert!(after > before, "no tokens received")
credit(owner: ctx.caller(), amount: after - before)
```

The mock token charges a 10% transfer fee. A deposit request for 100 units credits 90. Withdrawing that claim sends 90 gross units and the recipient receives 81 after the token's outbound fee. A fully taxed deposit reverts without credit. The vault assumes a truthful `balanceOf` and does not support rebasing or adversarial tokens.

## Auction refund

`RefundAuction` credits an outbid participant's previous bid and lets that participant pull the refund through `withdraw_and_dispatch`. It uses the same `Ledger` and `Native` adapter without a vault. It is a refund example, not a complete auction settlement protocol.

## What the compiler rejects

`compile-fail/run.sh` checks seven tiny programs against exact Fe 26.5.0 diagnostics. It fails if a bad program starts compiling or if the expected diagnostic changes.

| Bad program | Why it fails | Boundary |
| --- | --- | --- |
| Forge `Payout { ... }` before a commit | `error[2-0003]`: private fields are not visible | typed-cei privacy |
| Call the private `Payout::new` constructor | `error[2-0003]`: `new` is not visible | typed-cei privacy |
| Dispatch one payout twice | `error[16-0002]`: value was moved | typed-cei ownership API + Fe moves |
| Ignore a freshly returned payout | `error[8-0082]`: unused `#[must_use]` value | typed-cei annotation |
| Dispatch without `Ctx` / `Call` | `error[8-0036]`: missing effects | typed-cei effect signature |
| Add `Ledger` to an `Asset` implementation | `error[6-0009]`: method has stricter bounds than trait | typed-cei fixed trait effects |
| Hold mutable storage across an external call | `error[16-0001]`: access conflict | Fe's built-in access checker |

The last row is deliberately labeled as a Fe feature, not a library invention. `typed-cei` addresses the separate ordering gap after storage accesses have closed.

## Migration from manual CEI

Start with a hand-written withdrawal that debits before calling out:

```fe
Withdraw { to } -> u256 uses (ctx, mut call, mut balances) {
    let owner = ctx.caller()
    let amount = balances[owner]
    assert!(amount > 0, "nothing to withdraw")
    balances[owner] = 0
    assert!(
        call.send_value(addr: to, gas: ctx.gas(), value: wei(amount)).success(),
    )
    amount
}
```

Change the contract field from `mut balances: StorageMap<Address, u256>` to `mut ledger: Ledger`. Replace the deposit's direct map increment with `credit(owner: ctx.caller(), amount: ctx.value().as_wei())`. Then replace the withdrawal body with:

```fe
Withdraw { to } -> u256 uses (ctx, mut call, mut ledger) {
    withdraw_and_dispatch(owner: ctx.caller(), to, asset: native())
}
```

The one-call path handles the simple case. For split payouts, call `commit_split` once and dispatch both returned values after the debit. Keep all other business state consistent before an external call; the ledger type does not order unrelated fields.

Compile-time checks after migration:

| Mistake | Fe 26.5 diagnostic |
| --- | --- |
| Construct a payout or call its private constructor | `2-0003` (private) |
| Dispatch a moved payout a second time | `16-0002` (moved value) |
| Ignore a direct `Payout` return | `8-0082` (`must_use`) |
| Call `dispatch` without `Ctx` and `Call` | `8-0036` (missing effects) |
| Add `Ledger` effects to an asset adapter | `6-0009` (trait bound) |
| Keep mutable storage access open across a call | `16-0001` (access conflict) |

Run `FE_BIN=fe ./compile-fail/run.sh` to see all seven exact diagnostics, including the separate field-forgery fixture. An intentional discard through `let _ = commit_withdraw(...)` still compiles; the one-call path avoids exposing that value.

## Reentrancy demonstration

The same attacker is used against four contracts. A victim deposits 2 ETH; the attacker deposits 1 ETH and requests two re-entry rounds. The attacker records each nested withdrawal attempt and whether it succeeded.

| Contract | Nested attempts / successes | Attacker ends with | Victim claim | Vault ETH | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| `VulnerableVault` | 2 / 2 | 3 ETH | 2 ETH | 0 ETH | insolvent |
| `TypedVault` | 1 / 0 | 1 ETH | 2 ETH | 2 ETH | solvent |
| `ManualCeiVault` | 1 / 0 | 1 ETH | 2 ETH | 2 ETH | solvent |
| `GuardedVault` | 1 / 0 | 1 ETH | 2 ETH | 2 ETH | solvent |

The hand-written CEI baseline is intentional: debit-before-call is safe without this library. The runtime test demonstrates the ordering consequence; the compile-fail suite is what demonstrates the extra API constraints supplied by the typed pattern.

`typed_split_commits_before_both_callbacks` separately sends both split payouts back to the attacker. It observes two callback attempts and zero successful nested withdrawals, covering the two-interaction path rather than only EOA recipients.

The cross-function attack calls `withdrawSplit` from inside a `withdraw` payout callback. It first calls `balanceOf` to inspect the caller's claim:

| Contract | Nested split attempts / successes | Claim read during callback | Vault ETH after attack |
| --- | ---: | ---: | ---: |
| `TypedVault` | 1 / 0 | 0 ETH | 2 ETH |
| `ManualCeiVault` | 1 / 0 | 0 ETH | 2 ETH |
| `GuardedVault` | 1 / 0 | 1 ETH | 2 ETH |
| `VulnerableVault` | 2 / 2 | 1 ETH | 0 ETH |

All four tests start with a 2 ETH victim claim and a 1 ETH attacker claim. The vulnerable contract becomes insolvent. A separate read-only callback test performs only `balanceOf`. It sees zero during typed/manual dispatch but the old 1 ETH value during guarded/vulnerable dispatch. A guard blocks mutation, not stale read-only observations.

`discarding_payout_can_strand_committed_funds` is the negative boundary test: an intentionally wrong harness contract compiles with `let _ = commit_withdraw(...)`. It zeros a 1 ETH claim without paying it out, leaving that ETH stranded in the contract.

## Gas comparison

The four `gas_*` tests deploy a vault, deposit 1 ETH, then withdraw to the same empty-code recipient **in one EVM test transaction**. The measured withdrawal delta is `before - evm.gas()` at `-O 2`. The table subtracts the storage refunds generated by that same test transaction.

| Variant | Gross gas | SSTORE refund | Refund-adjusted net | Net delta vs manual |
| --- | ---: | ---: | ---: | ---: |
| hand-written CEI | 35,375 | 19,900 | 15,475 | baseline |
| typed CEI, one call | 35,409 | 19,900 | 15,509 | +34 |
| transient `TSlot<bool>` guard | 35,709 | 19,900 | 15,809 | +334 |
| persistent `bool` guard | 57,606 | 39,800 | 17,806 | +2,331 |

In this fixture, the ledger slot starts at zero, is written by the deposit, then reset by the withdrawal. EIP-2200/EIP-3529 credit 19,900 gas for that reset. The persistent guard also resets a zero-origin lock slot, earning another 19,900. The transient guard uses `TLOAD/TSTORE` and earns no lock refund. The test records create+deposit+withdraw gas; even this lower bound exceeds five times the refund for every variant, so the EIP-3529 20% refund cap does not bind.

The net values are deterministic refund accounting from this EVM test, not separate transaction receipts. A real withdrawal in a later transaction has different storage history and refund limits. Neither the guard comparison nor the 34-gas typed overhead is a general EVM gas claim.

Reproduce it with:

```sh
FE_BIN=fe ./scripts/measure-gas.py
```

The script requires four distinct gas-sample events. It checks the refund cap against recorded gas use and rejects missing, duplicate, or unaccountable samples.

## Build, test, and demo

Exact compiler used:

```text
fe 26.5.0 (3dab95f)
```

With Fe 26.5.0 on `PATH`:

```sh
fe --version
fe fmt --check
fe fmt --check test_harness
fe check
fe test test_harness
./compile-fail/run.sh
fe build
./scripts/measure-gas.py
```

The shortest security demo is:

```sh
fe test --filter vulnerable_control_is_drained_by_reentrancy test_harness
fe test --filter typed_cei_preserves_solvency_under_same_attack test_harness
fe test --filter cross_function_ test_harness
fe test --filter readonly_callback_ test_harness
fe test --filter erc20_ test_harness
./compile-fail/run.sh
```

Expected: all selected runtime tests pass, and all seven compile-fail cases print `PASS`.

## Architecture

| Path | Role |
| --- | --- |
| `src/ledger.fe` | private payout construction and ledger commits |
| `src/assets.fe` | generic fixed-effect asset interface; native ETH and ERC20 adapters |
| `src/vault.fe` | worked typed-CEI vault |
| `src/token_vault.fe` | ERC20 transfer-in accounting and payout |
| `src/auction.fe` | typed auction-refund example |
| `test_harness/src/manual.fe` | hand-written CEI control |
| `test_harness/src/vulnerable.fe` | interaction-before-effect exploit control |
| `test_harness/src/guarded.fe` | persistent-storage lock comparison |
| `test_harness/src/transient.fe` | `TSlot<bool>` guard comparison |
| `test_harness/src/lib.fe` | attacker, fee token, discard witness, functional tests, gas samples |
| `compile-fail/` | bad programs plus exact expected compiler diagnostics |
| `scripts/measure-gas.py` | reproducible four-way gross and net comparison |

The root ingot exports the three worked contracts, ledger/payout API, and asset API. Vulnerable, manual, guarded, transient, attacker, and mock-token contracts live in `test_harness`; a normal `fe build` does not ship those controls.

## What the types do not prevent

This is a narrow pattern, not a smart-contract verifier.

- A contract author can bypass the library and use raw `Call` directly. The compiler does not globally require every external call to consume a `Payout`.
- The trusted accounting module itself must remain correct. Module privacy prevents outside code from forging `Payout`, but it does not prove that future edits inside `ledger.fe` keep the constructor after the debit.
- Fe 26.5 does not enforce full linearity: `let _ = commit_withdraw(...)` can still discard a committed payout, so simple withdrawals should use `withdraw_and_dispatch` instead.
- The pattern ties one ledger debit to one or more payout capabilities. It does not require every other state update in a handler to happen before interaction. Cross-function invariants, fees, counters, authorization, oracle logic, and recipient correctness remain application concerns.
- The fixed `Asset` effect row prevents an adapter from directly requiring `Ledger`, but the adapter still has `Call` and can invoke arbitrary external code. Application-level reentrancy and callback policy still matter beyond the protected ledger claim.
- `credit` / `commit_*` are low-level accounting primitives that accept an explicit `owner`. The worked vault binds that owner to `ctx.caller()`; other callers must enforce their own authorization before using the primitives.
- The ERC20 vault checks received balances but assumes a truthful, non-rebasing token. Transfer fees on outgoing payouts reduce the amount the recipient receives.
- Fe 26.5 is explicitly not production-ready. This is a contest prototype and security-pattern experiment, not audited production code.

## Fe-specific pieces that carry real weight

**Effects.** `Ledger`, `Ctx`, and `Call` authority is visible in signatures. The asset trait fixes dispatch to `(Ctx, mut Call)`, and Fe rejects implementations that widen that effect set.

**Ownership.** `dispatch(own self)` moves the payout. A second dispatch is a compile-time move conflict.

**Module privacy.** A public `Payout<A>` can have private fields and a private constructor. Callers can carry the capability without receiving minting authority.

**Traits and generics.** The same `Payout<A>` and commit functions work for native ETH and ERC20-style assets while enforcing one effect contract for every adapter.

**Message groups and the EVM test effect.** The controls share the same `VaultMsg` ABI, and the attacker exercises real nested contract calls under Fe's `Evm` test provider.

## Disclosure and license

See [`AI_DISCLOSURE.md`](AI_DISCLOSURE.md). The project began from the official Fe Builders Challenge starter and uses Fe 26.5 standard-library/compiler behavior as reference material. No code from another contest entry was used.

Apache-2.0. See [`LICENSE`](LICENSE).
