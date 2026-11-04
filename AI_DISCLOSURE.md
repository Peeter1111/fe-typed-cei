# AI disclosure

This project was built with AI assistance from ChatGPT worker chats. AI assistance was used for Fe language/compiler research, design iteration, implementation, tests, documentation drafting, and command-driven verification.

No generated result was treated as evidence on its own. Security claims in the README are tied to compiler diagnostics, runtime tests, or reproducible commands in this repository. Gas numbers come from `scripts/measure-gas.py` and the Fe test harness.

## Claude review

Claude Code 2.1.318 performed two read-only static review passes of the implementation and submission material on November 4, 2026. Its shell access was intentionally disabled for those reviews, so it did not independently run tests. The second pass reported no high-severity issue in the code or the narrowed security guarantee; remaining actionable wording/test-hygiene findings were then addressed and verified with the local Fe toolchain.

Among the review findings addressed before final validation: the original pitch overstated global enforcement; the first gas comparison lacked a hand-written CEI baseline and refund caveat; the reentrancy tests did not record nested-call success directly; the first asset design used an unnecessary sealed associated-effect row; and test-only contracts were emitted by the root build. The final design uses a fixed `(Ctx, mut Call)` trait effect, includes a manual CEI gas baseline, records nested attempts/successes, narrows the claims in the README, and moves controls/attack helpers into a separate test-harness ingot.

## Human check before submission

This checklist is intentionally left unchecked for the project lead to complete against the final public commit.

- [ ] Read the README and `SUBMISSION.md` against the final commit.
- [ ] Confirm the seven compile-fail diagnostics on Fe 26.5.0.
- [ ] Re-run the vulnerable and typed reentrancy tests.
- [ ] Re-run the gas script and confirm the reported values.
- [ ] Review the “What the types do not prevent” section for overclaims.
- [ ] Confirm the Claude-review changes still match the final implementation.
- [ ] Supply the final public repository URL and full commit SHA in the contest submission form.

## Pre-existing work

Before this project, the repository used the official Fe Builders Challenge starter. The implementation also relies on the Fe 26.5 standard library and public compiler/documentation behavior as reference material. No code from another contest entry was used.
