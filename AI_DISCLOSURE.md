# AI disclosure

AI assistants helped research Fe 26.5, design the API, write and review code, build tests, and draft documentation. The implementation was checked with the local Fe compiler. The tests and benchmark can be reproduced with the commands in the README.

The code has not received an independent security audit. Compiler diagnostics and EVM tests establish only the specific claims described in the README.

The project uses the official Fe Builders Challenge starter and Fe's standard library and public documentation. No code from another contest entry was used.

## Review before submission

No human programmer reviewed this code. The entrant, Peeter Tsanev, is not a programmer. He chose to enter and approved publishing. AI agents did the design, the implementation and every review:

- ChatGPT worker chats wrote the implementation, tests, scripts and documentation.
- Claude wrote the project brief and read every file in `src/` on November 9, 2026.
- OpenAI Codex, in a separate session, built the earlier and the current revision on November 9, 2026, and wrote 5 regression checks. Each check fails on the earlier revision and passes on the current one.
