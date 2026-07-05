# Changelog

All notable changes to Context-Lens. Versioning is [SemVer](https://semver.org);
`plugin.json` carries an explicit `version` so users get updates only on a bump.

## [1.1.0] — 2026-07-05

Dashboard reaches the browser and tracks the session more closely.

### Added
- **`/context-lens` opens the dashboard** — new `analyzer.py --open` launches the live
  `report.html` in your browser (on WSL, the Windows default browser via a `wslpath`-
  translated path) and prints the URL as a fallback. Renders the file first if no turn has
  written one yet.
- **Intra-turn refresh** — a `PostToolUse` hook (`analyzer.py --refresh`) rewrites the
  dashboard after every tool call, so composition, dead weight, and signals move *within* a
  turn instead of only at turn end. Zone-crossing warnings stay owned by the `Stop` hook
  (once per turn). Meta-refresh tightened to 2s.

### Notes
- Requires `/reload-plugins` (or a new session) to arm the `PostToolUse` hook.
- The headline **token gauge still steps at turn end** — the model's token `usage` only
  lands in the transcript then. Everything else moves per tool call. A continuously-moving
  gauge would need a local server (out of scope; keeps the no-server/no-dep/`file://` design).

## [1.0.0] — 2026-07-05

First stable release. Full LOCA-bench context-rot loop, packaged for marketplace install.

### Added
- **Four-signal rot score** (S1 load, S2 exploration plateau, S3 dead weight,
  S4 instruction distance), weighted `.35/.25/.25/.15`, mapped to LOCA-bench failure modes.
- **`/context-lens` report** — on-demand terminal breakdown: score, zone, composition,
  top dead weight safe to clear.
- **Live HTML dashboard** — self-contained (no JS, no CDN), meta-refresh, dark/light aware;
  model header, context gauge, rot dial, regime banner, composition donut, rot-trend
  sparkline. Rewritten each turn by the Stop hook.
- **Statusline gauge** (optional, one manual settings line) — zone-colored bar + rot score.
- **Zone-crossing awareness** — Stop hook warns the user (`systemMessage`); on a *worsening*
  crossing a ~90-token context-awareness note is delivered to the model at the next prompt
  (UserPromptSubmit hook) — the paper's measured mitigation.
- **Compaction loop** — PreCompact snapshots context; the next turn reports the before/after
  diff (dead weight cleared vs live state lost) plus a lossy-summary caution to the model.
- Marketplace packaging (`marketplace.json`), MIT license, this changelog.

### Notes
- Composition figures and S2/S4 are estimates (chars/4 token proxy, ±15%); score
  thresholds are calibration knobs at the top of `analyzer.py`.
- Plugins cannot auto-set the main statusline — the gauge needs one manual `settings.json`
  line (see README).
