# typed-cei

**Pitch:** Move one checks-effects-interactions boundary from a review convention into a compiler-checked API: public ledger commits mint opaque payouts, and payout dispatch has `Ctx + Call` authority but no `Ledger` authority.

## The problem

Fe's access checker already rejects external calls while a conflicting storage access is open. It intentionally permits a call between closed accesses, so classic code that copies a balance, calls out, and only then writes zero can still compile.

`typed-cei` gives library and contract authors a small API for one important order: debit before dispatch. A single-call function commits and sends; an opaque payout remains available for batches and splits.

## Approach

`Payout<A>` has private fields and a private constructor. `commit_withdraw` and `commit_split` require `mut Ledger`, write the debit first, and return payout values. `Payout::dispatch(own self)` consumes the value and requires only `(Ctx, mut Call)`. `withdraw_and_dispatch` performs both actions without exposing a payout to the caller.

The generic `Asset` trait fixes that same effect row. Third-party adapters can implement it, but Fe rejects any implementation that tries to add `mut Ledger` as a stricter method bound.

The repository includes worked ETH and ERC20 vaults, an auction refund, native and safe-ERC20 adapters, a vulnerable control, a hand-written CEI baseline, persistent and transient guards, a reentrant attacker, seven compile-fail fixtures, and a four-way gas benchmark.

## Fe highlight

```fe
pub fn commit_withdraw<A: Asset>(owner: Address, to: Address, asset: own A) -> Payout<A>
uses (ledger: mut Ledger)
{
    let amount = ledger.balances[owner]
    assert!(amount > 0, "nothing to withdraw")
    ledger.balances[owner] = 0
    Payout::new(asset, to, amount)
}

pub fn withdraw_and_dispatch<A: Asset>(owner: Address, to: Address, asset: own A) -> u256
uses (ledger: mut Ledger, ctx: Ctx, call: mut Call)
{
    let payout = commit_withdraw(owner, to, asset)
    let amount = payout.amount()
    payout.dispatch()
    amount
}

pub trait Asset {
    fn send(own self, to: Address, amount: u256) uses (ctx: Ctx, call: mut Call)
}

impl<A: Asset> Payout<A> {
    pub fn dispatch(own self) uses (ctx: Ctx, call: mut Call) {
        self.asset.send(to: self.to, amount: self.amount)
    }
}
```

The compiler rejects payout forgery, double dispatch, missing call effects, asset implementations that add ledger authority, and—via Fe's own access checker—external calls across open mutable storage access.

## Architecture

- `ledger.fe`: accounting plus opaque payout values.
- `assets.fe`: open generic asset interface with a fixed external-call effect contract; native ETH and ERC20 implementations.
- `vault.fe`: worked typed-CEI vault with deposit, withdraw, and split payout.
- `token_vault.fe`: token intake with `safe_transfer_from` and actual received-balance accounting.
- `auction.fe`: small outbidder refund example using the same one-call withdrawal.
- `test_harness/src/manual.fe`: safe hand-written CEI baseline.
- `test_harness/src/vulnerable.fe`: legal Fe code with interaction before effect, used as the exploit control.
- `test_harness/src/guarded.fe`: the same ABI protected by a persistent `bool` storage lock.
- `test_harness/src/transient.fe`: comparison using Fe's transient `TSlot<bool>`.
- `test_harness/src/lib.fe`: nested-call attacker, ERC20 mock, functional and gas tests.
- `compile-fail/`: exact diagnostics for seven prohibited shapes.

## Build and test

Compiler used: `fe 26.5.0 (3dab95f)`.

```sh
fe fmt --check
fe fmt --check test_harness
fe check
fe test test_harness
./compile-fail/run.sh
fe build
./scripts/measure-gas.py
```

No non-standard Python packages are required.

## Demo

```sh
fe test --filter vulnerable_control_is_drained_by_reentrancy test_harness
fe test --filter typed_cei_preserves_solvency_under_same_attack test_harness
fe test --filter cross_function_ test_harness
fe test --filter readonly_callback_ test_harness
fe test --filter erc20_ test_harness
./compile-fail/run.sh
```

The vulnerable vault records two successful nested withdrawals, pays the attacker 3 ETH, retains 0 ETH, and still owes a victim 2 ETH. Under the same attacker, the typed vault records one failed nested withdrawal, pays only the attacker's own 1 ETH, and retains the victim's 2 ETH. A hand-written CEI control is also safe; the compiler-facing value of this project is the API boundary, not a claim that CEI itself requires new runtime machinery.

A separate split-payout attack sends both post-commit payouts to the attacker and records two callbacks with zero successful nested withdrawals.

The cross-function attacker calls `balanceOf` then `withdrawSplit` during `withdraw` dispatch. Typed, manual, and guarded controls reject the nested split; the vulnerable vault loses 3 ETH. Read-only tests show the guarded/vulnerable contracts expose stale accounting during dispatch, unlike typed/manual CEI.

The ERC20 vault credits the balance increase after `transferFrom`. A 10% fee mock credits 90 after a 100-unit deposit, and its 90-unit withdrawal delivers 81. An outbid participant can claim their ETH through the auction-refund example.

The `DiscardVault` limitation test confirms that `let _ = commit_withdraw(...)` still compiles and can strand 1 ETH. `withdraw_and_dispatch` keeps that obligation inside the library for the common case and reverts the debit when a send fails.

At `-O 2`, the same-transaction synthetic withdrawal uses gross gas 35,375 manual, 35,409 typed, 35,709 transient guard, 57,606 persistent guard. EIP-3529 refund-adjusted results are 15,475 / 15,509 / 15,809 / 17,806 respectively; the script verifies the refund cap is nonbinding in the harness. The typed overhead is 34 gas. These numbers do not describe a separate mainnet withdrawal transaction.

## Limitations

The pattern does not prevent bypassing it with raw `Call`, discarding a bound payout, incorrect edits to trusted accounting, or unrelated state/authorization errors. Asset adapters still have `Call` authority. Token intake trusts the token's balance reporting and excludes rebasing tokens; outbound transfer fees reduce receiver amounts. The auction demonstrates refunds but not settlement. Fe 26.5 is not production-ready, and this code has not been security audited.

## Declaration

- **Pre-existing work:** the official Fe Builders Challenge starter and Fe 26.5 standard-library/compiler reference material. The typed CEI design, contracts, tests, compiler fixtures, and benchmark were written in this repository during the contest window.
- **Third-party code:** no third-party source was copied into the implementation. The project imports the Fe standard library supplied with Fe 26.5.0. The starter's Apache-2.0 license is retained.
- **AI assistance:** documented in `AI_DISCLOSURE.md`.

## Team

Peeter Tsanev.

## License

Apache-2.0.
