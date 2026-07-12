# Contributing to Context Lens

Thanks for helping make AI coding sessions more observable and recoverable.

## Good first contributions

- Reproducible transcript fixtures with sensitive content removed.
- Tests for parsing, scoring boundaries, compaction, and dashboard rendering.
- Documentation and installation improvements.
- Research notes about stable Claude Code, Codex, or OpenCode telemetry.
- Proposals for the portable event schema or adapter contract.

Open an issue before implementing a new host adapter or changing score semantics. Those changes need
a small design discussion so the core remains portable and existing reports remain comparable.

## Development setup

The current analyzer uses the Python standard library only.

```bash
git clone https://github.com/edwinidrus/Context-lens.git
cd Context-lens
python3 test_analyzer.py
```

The expected result is `test_analyzer: ALL PASS`. Claude Code integration checks are documented in
[MANUAL-TEST.md](MANUAL-TEST.md).

## Pull requests

- Keep changes focused and explain the user-facing problem they solve.
- Add or update deterministic tests for behavioral changes.
- Preserve local-first operation and avoid new runtime dependencies without a clear justification.
- Label estimated or experimental measurements honestly.
- Do not commit real transcripts, prompts, credentials, private paths, or source-code excerpts from
  a user's session.
- Update `CHANGELOG.md` for externally visible changes.

Bug reports are most useful when they include the host, Context Lens version, expected behavior,
actual behavior, and the smallest anonymized fixture that reproduces the issue.
