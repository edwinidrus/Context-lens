# Changelog

All notable changes to Context-Lens. Versioning is [SemVer](https://semver.org);
`plugin.json` carries an explicit `version` so users get updates only on a bump.

## [Unreleased]

### Added
- Long-term vendor-neutral product vision and phased roadmap for Claude Code, Codex, OpenCode,
  recovery workflows, and an adapter ecosystem.
- Contributor guidance and repository instructions for consistent future development.
- Reproducible LOCA-bench context-length versus task-accuracy diagram, its published source data,
  and a dependency-free SVG renderer.

### Changed
- README now clearly separates the working Claude Code release from planned platform support and
  documents installation, scoring, privacy, development, and project direction.

## [1.3.0] — 2026-07-12

Codex sessions can now join the same local command center with capability-aware fidelity.

### Added
- **Installable Codex plugin** — `.codex-plugin/plugin.json`, Codex-compatible lifecycle hooks,
  and a dependency-free local marketplace builder.
- **Codex lifecycle adapter** — tracks ready, running, waiting, permission-attention, compaction,
  turn, and tool-event state without reading prompts or tool content.
- **Combined host-neutral cache** — new summaries live under `~/.context-lens/`; existing Claude
  cache state remains readable as a compatibility fallback.

### Notes
- Codex hooks do not currently expose stable context-token or S1-S4 inputs, so its cards label
  those fields unavailable. The adapter does not parse the documented-unstable transcript format.
- Codex does not currently expose `SessionEnd`; inactivity after 30 minutes is visibly labeled as
  an estimate rather than treated as an observed end event.
- Plugin hooks require explicit review and trust through Codex `/hooks` before they run.

## [1.2.0] — 2026-07-12

One local view can now follow every Context Lens-enabled Claude Code session.

### Added
- **`/context-lens-monitor` command center** — opens a dependency-free, self-refreshing overview
  of active, attention-needed, RED, and recently ended sessions on the current machine.
- **Lifecycle tracking** — `SessionStart`, `SessionEnd`, and `Notification` hooks record ready,
  running, waiting, compacting, needs-attention, and ended phases without reading transcript text.
- **Versioned privacy-minimized summaries** — each session writes raw health observations and
  derived signals in separate fields for the aggregate dashboard.

### Notes
- Monitoring is local, read-only, and limited to Claude Code. It sends no telemetry and displays
  no prompts, source code, tool output, transcript paths, or full working-directory paths.
- Reload plugins or start a new session to arm the additional lifecycle hooks. Sessions already
  running appear after their next Context Lens hook event.

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
