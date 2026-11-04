# typed-cei

**Move one checks-effects-interactions boundary from a review convention into a compiler-checked API: public ledger commits mint opaque payouts, and payout dispatch has `Ctx + Call` authority but no `Ledger` authority.**

`typed-cei` is a small Fe 26.5 library plus a worked ETH vault. It does not claim to make arbitrary Fe code reentrancy-safe. It makes a narrower property hard to violate when code uses the library: a caller cannot forge a payout, cannot dispatch the same payout twice, and cannot widen an asset adapter's dispatch effects to include the ledger.

```text
commit_withdraw(...)  uses (ledger: mut Ledger)
        │
        └──> Payout<Native>       private fields; caller cannot forge it
                  │
                  └──> dispatch() uses (Ctx, mut Call); no Ledger effect
```

The repository includes a deliberately vulnerable vault, a hand-written CEI baseline, a persistent-storage reentrancy guard, a real reentrant attacker, exact compile-fail diagnostics, and a reproducible gas comparison.

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

The library adds a second boundary after Fe's built-in access checking. Its trusted accounting module owns the `Payout` constructor. The only public commit functions in that module debit storage before returning a payout. Code outside the module can hold and consume that value, but cannot construct one directly.

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

## Worked vault

`TypedVault` supports payable `deposit()`, `withdraw(address)`, `withdrawSplit(address,address,uint256)`, and `balanceOf(address)`.

The normal withdrawal is deliberately small:

```fe
let payout = commit_withdraw(owner: ctx.caller(), to, asset: native())
let amount = payout.amount()
payout.dispatch()
amount
```

`commit_split` shows composition: one committed debit can return two independently consumable payouts, then both interactions happen after the ledger write.

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

There is also a mock ERC20 test that moves 250 token units through `Payout<Erc20Asset>` and verifies the receiver's token balance.

## Gas comparison

The benchmark measures the remaining-gas delta (`before - evm.gas()`) around one optimized (`-O 2`) withdrawal call after each contract has already received the same 1 ETH deposit. All three pay the same empty-code recipient.

| Variant | Gross gas before refunds | Delta vs manual CEI |
| --- | ---: | ---: |
| hand-written CEI | 35,375 | baseline |
| typed CEI | 35,409 | +34 (+0.10%) |
| persistent `false → true → false` storage guard | 57,606 | +22,231 (+62.84%) |

Three consecutive local runs produced the same numbers. The primary abstraction result is the absolute delta: typed CEI costs 34 gross gas over hand-written CEI in this benchmark. The shared value-transfer/new-account CALL costs dominate the total, which is why that 34-gas delta is only 0.10%.

The storage-guard number is intentionally specific: it is the conventional persistent `bool` guard in `test_harness/src/guarded.fe`, not an optimized sentinel scheme and not Fe's transient-storage `Mutex`. The measured remaining-gas delta is gross execution gas; transaction-level SSTORE refunds are **not** subtracted. So the 62.84% figure is a gross-before-refunds comparison, not a claim about every reentrancy guard's net transaction cost.

Reproduce it with:

```sh
FE_BIN=fe ./scripts/measure-gas.py
```

The script requires exactly three gas-sample events with distinct kinds 1, 2, and 3, and rejects missing, extra, or duplicate kinds.

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
fe test test_harness
./compile-fail/run.sh
fe build
./scripts/measure-gas.py
```

The shortest security demo is:

```sh
fe test --filter vulnerable_control_is_drained_by_reentrancy test_harness
fe test --filter typed_cei_preserves_solvency_under_same_attack test_harness
./compile-fail/run.sh
```

Expected: both runtime tests pass, and all seven compile-fail cases print `PASS`.

## Architecture

| Path | Role |
| --- | --- |
| `src/ledger.fe` | private payout construction and ledger commits |
| `src/assets.fe` | generic fixed-effect asset interface; native ETH and ERC20 adapters |
| `src/vault.fe` | worked typed-CEI vault |
| `test_harness/src/manual.fe` | hand-written CEI control |
| `test_harness/src/vulnerable.fe` | interaction-before-effect exploit control |
| `test_harness/src/guarded.fe` | persistent-storage lock comparison |
| `test_harness/src/lib.fe` | attacker, mock ERC20, functional tests, gas samples |
| `compile-fail/` | bad programs plus exact expected compiler diagnostics |
| `scripts/measure-gas.py` | reproducible three-way gas comparison |

The root ingot's public surface exports only the typed vault, ledger/payout API, and asset API. Vulnerable, manual, guarded, attacker, and mock-token contracts live in the separate `test_harness` ingot, so a normal `fe build` of the library does not ship those controls.

## What the types do not prevent

This is a narrow pattern, not a smart-contract verifier.

- A contract author can bypass the library and use raw `Call` directly. The compiler does not globally require every external call to consume a `Payout`.
- The trusted accounting module itself must remain correct. Module privacy prevents outside code from forging `Payout`, but it does not prove that future edits inside `ledger.fe` keep the constructor after the debit.
- `#[must_use]` rejects an immediately ignored payout, but Fe is affine here, not fully linear. Code can bind a payout and never dispatch it, or explicitly write `let _ = ...`; that can strand a committed claim even though it cannot duplicate the payout.
- The pattern ties one ledger debit to one or more payout capabilities. It does not require every other state update in a handler to happen before interaction. Cross-function invariants, fees, counters, authorization, oracle logic, and recipient correctness remain application concerns.
- The fixed `Asset` effect row prevents an adapter from directly requiring `Ledger`, but the adapter still has `Call` and can invoke arbitrary external code. Application-level reentrancy and callback policy still matter beyond the protected ledger claim.
- `credit` / `commit_*` are low-level accounting primitives that accept an explicit `owner`. The worked vault binds that owner to `ctx.caller()`; other callers must enforce their own authorization before using the primitives.
- The worked contract is an ETH vault. ERC20 payout dispatch is tested with a local mock token; a production token vault would also need transfer-in accounting and token-specific policy.
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
