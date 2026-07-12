# Context Lens repository guide

## Mission

Context Lens is becoming a local-first, vendor-neutral observability and recovery layer for AI
coding sessions. The working `v1.x` product supports full context-health analysis for Claude Code
and limited-fidelity lifecycle monitoring for Codex. Codex context-token/S1-S4 telemetry, OpenCode,
and additional hosts remain roadmap targets until stable, tested inputs exist. Read `VISION.md`
before making architectural or product-positioning changes.

## Current architecture

- `scripts/analyzer.py` contains the Claude transcript parser, S1-S4 scoring, reports, state,
  dashboard rendering, compaction handling, and CLI. It must remain fast and dependency-free unless
  a deliberate architecture change is accepted.
- `hooks/hooks.json` wires Claude Code lifecycle events to the analyzer.
- `skills/context-lens/SKILL.md` provides the `/context-lens` behavior.
- `scripts/statusline.sh` is the statusline entry point.
- `.claude-plugin/` contains the plugin and marketplace manifests.
- `.codex-plugin/` contains the Codex plugin manifest; `scripts/build_codex_marketplace.py` creates
  the installable local artifact with the Codex-supported hook subset.
- `test_analyzer.py` is the deterministic regression suite.

## Product and engineering rules

- Do not claim support for a host until an installable, tested integration exists.
- Keep raw observations separate from derived scores when extracting the portable core.
- Treat thresholds and weights as visible calibration knobs, not universal truths.
- Label estimates, missing telemetry, confidence limits, and experimental signals.
- Keep transcript analysis local by default and never add telemetry silently.
- Recovery actions that mutate session state must be explicit, previewable, and reversible.
- Prefer a host-neutral core plus thin native adapters over host checks spread through the analyzer.
- Preserve the existing Claude Code experience while refactoring toward multi-host support.

## Validation

Run the offline suite after any functional change:

```bash
python3 test_analyzer.py
```

Validate both plugin surfaces after packaging changes:

```bash
claude plugin validate .
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
```

For plugin wiring and dashboard checks, follow `MANUAL-TEST.md`. Never use or commit a real user
transcript as a fixture; create a minimal anonymized JSONL file instead.
