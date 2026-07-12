# Context Lens

**Know when an AI coding session is losing the plot — before the answer quality does.**

Context Lens is an open-source observability and recovery toolkit for long-running AI coding
sessions. It turns an invisible context window into actionable signals: how much context is in
use, which content has become dead weight, whether exploration is slowing down, and when the
active instructions are becoming too distant.

The current `v1.x` release is a working **Claude Code plugin**. The long-term product is a
vendor-neutral layer for Claude Code, Codex, OpenCode, and other agentic development tools.
See [VISION.md](VISION.md) for the product direction and roadmap.

## Why Context Lens?

AI coding agents rarely fail only because they hit a hard token limit. Quality can decline
earlier: constraints fade, repeated tool output accumulates, exploration narrows, and a compacted
summary can lose an important fact. Context Lens makes those conditions visible and recommends a
recovery action while the session is still useful.

The current scoring model is informed by the four long-context failure modes described in
[LOCA-bench](https://arxiv.org/html/2602.07962v1). It is an operational heuristic, not a claim to
measure model intelligence or answer correctness.

## The benchmark signal behind Context Lens

![LOCA-bench task success accuracy falls as environment description length grows](images/loca-bench-context-quality.svg)

> **Data currency — checked 12 July 2026:** this is the newest reliable, like-for-like
> 8K–256K model sweep I could verify from the
> [LOCA-bench paper](https://arxiv.org/html/2602.07962v1) and
> [official repository](https://github.com/hkust-nlp/LOCA-bench). The repository does not publish a
> live leaderboard or a newer model-results table. A newer
> [VISTA study](https://arxiv.org/abs/2606.30005v2) reports LOCA-bench context-management results,
> including a Gemini-3-Flash improvement, but I could not verify from it a replacement
> same-protocol 8K–256K curve for newer model releases. The diagram therefore keeps the published
> model set and does **not** estimate or substitute results for newer models.

This chart reproduces the published values from
[LOCA-bench Table 1](https://arxiv.org/html/2602.07962v1#S2.T1). The benchmark holds the task family
constant while increasing **environment description length** from 8K to 256K tokens, then measures
whether an agent successfully changes the environment to the verified ground-truth state. It covers
15 agentic tasks, five random seeds, and 75 samples at each length (525 total).

The y-axis is therefore execution-verified **task success accuracy**, a concrete measure of agentic
inference quality—not a universal score for every prompt. All seven reported models deteriorate as
the context workload grows. The authors also report that the gap becomes pronounced around 32K and
that exploration tends to plateau after 96K. This gradual, pre-limit degradation is the problem
Context Lens is designed to make visible during real development sessions.

> **Method caveat:** environment description length measures the tokens needed to encode the
> task's environment, not the exact prompt size at every agent turn. LOCA-bench uses each model's
> maximum supported window and retains the most recent tokens when an input exceeds that limit. See
> the [paper](https://arxiv.org/html/2602.07962v1) and
> [official benchmark repository](https://github.com/hkust-nlp/LOCA-bench) for the full protocol.

The source values are committed in
[`benchmarks/loca-bench-table-1.csv`](benchmarks/loca-bench-table-1.csv); regenerate the SVG with:

```bash
python3 scripts/render_loca_benchmark.py
```

## What works today

- **Statusline** — an always-on context gauge with the current health regime.
- **`/context-lens` report** — an on-demand breakdown of load, dead weight, exploration, and
  instruction distance.
- **Live dashboard** — a self-contained, auto-refreshing HTML view with no server or runtime
  dependencies.
- **All-session monitor** — a local command center for watching lifecycle state, telemetry
  coverage, and attention needs across active Claude Code and Codex sessions on the machine.
- **Proactive warnings** — GREEN, AMBER, and RED transitions for both the developer and agent.
- **Compaction feedback** — a before/after view of what `/compact` removed, plus a reminder to
  verify facts that may have been lost in summarization.
- **Privacy-first analysis** — session data stays local; Context Lens does not send transcripts to
  an external service.

Current platform support:

| Platform | Status | Notes |
| --- | --- | --- |
| Claude Code | Available | Hooks, skill, statusline, terminal report, and dashboard |
| Codex | Available (limited fidelity) | Installable plugin, lifecycle hooks, attention state, compaction/event counts, and dashboard; context tokens and S1–S4 unavailable |
| OpenCode | Planned | Event adapter and shared analysis engine |
| Other agent tools | Future | Supported through a documented adapter contract |

## Install for Claude Code

Clone the repository, then add it as a local marketplace:

```bash
git clone https://github.com/edwinidrus/Context-lens.git
cd Context-lens
claude plugin validate .
claude plugin marketplace add "$(pwd)"
claude plugin install context-lens@context-lens
```

Start a fresh Claude Code session, or run `/reload-plugins`, then use:

```text
/context-lens           # current session report and dashboard
/context-lens-monitor   # all local sessions
```

Both commands open a self-refreshing dashboard and print its local `file://` URL as a fallback.
The all-session monitor shows health metadata only: project basename, model, lifecycle phase,
context load, S1–S4, score, zone, and update freshness. It does not display prompts, source code,
tool output, transcript paths, or full working-directory paths. Ended sessions remain visible for
24 hours (up to 20 cards), while older local cache data is left untouched. See
[MANUAL-TEST.md](MANUAL-TEST.md) for the statusline setup and complete verification flow.

## Install for Codex

Build a clean local marketplace from the clone, register it, and install the plugin:

```bash
python3 scripts/build_codex_marketplace.py ~/.codex/context-lens-marketplace-1.3.0
codex plugin marketplace add ~/.codex/context-lens-marketplace-1.3.0
codex plugin add context-lens@context-lens-local
```

Start a new Codex thread. Open `/hooks`, review the bundled command hooks, and trust their current
definition; Codex intentionally skips untrusted plugin hooks. Then use `/context-lens` for the
current session or `/context-lens-monitor` for the combined local command center.

Codex support is intentionally honest about its lower telemetry fidelity. Stable Codex hooks expose
session ID, project, model, phase, tools, turns, permission requests, and compaction events, but not
the context-token and signal inputs required for S1–S4. Context Lens therefore shows those scores as
**unavailable** instead of parsing Codex's explicitly unstable transcript format. Because Codex has
no documented `SessionEnd` hook, a session with no event for 30 minutes moves to **Inactive
(estimated)**; its cached data is not deleted. Shared state lives under `~/.context-lens/`.

## How the score works

The Claude Code adapter reads the local JSONL transcript and derives four signals:

| Signal | What it approximates | Current weight |
| --- | --- | ---: |
| S1 · load | Risk associated with deep context usage | 35% |
| S2 · exploration | Decline in tool-call cadence across the session | 25% |
| S3 · dead weight | Superseded output from repeated tool calls | 25% |
| S4 · instruction distance | Distance from the latest genuine user instruction | 15% |

The combined score maps to GREEN, AMBER, or RED. Thresholds and weights are intentionally
visible calibration knobs in [`scripts/analyzer.py`](scripts/analyzer.py), and estimated values
are labeled as estimates.

### Model and context-window detection

Context Lens does not maintain a hardcoded model-name or context-window catalogue. It reads the
model identifier emitted by the runtime and creates the display label algorithmically, so Claude,
GPT, Gemini, and open-weight model IDs do not require analyzer changes when new names are released.
This identifier compatibility is separate from host support. Codex now has an installable,
lifecycle-only adapter; Gemini and open-weight hosts still require their own tested integrations.

The context-window diagram uses capacity metadata advertised by the hook or transcript, including
common fields such as `context_window_tokens`, `max_context_tokens`, `context_length`, and `n_ctx`.
This matters for open-weight deployments, where the serving configuration can change the usable
window for the same model. When a runtime does not expose capacity, Context Lens shows a visibly
labeled 200K estimate instead of guessing from the model name. Set a local deployment-specific
override when needed:

```bash
export CONTEXT_LENS_CONTEXT_WINDOW=131072
```

The override remains local, requires no network request, and applies to subsequent analyzer hook
invocations. Explicit runtime metadata and overrides are recorded with their source and confidence
in the local session summary.

## Where this is going

Context Lens is evolving from a single-host plugin into a portable context-health system:

1. Extract the current analyzer into a host-neutral core with versioned event and signal schemas.
2. Complete Codex health telemetry when stable inputs become available, then add OpenCode without
   reducing the fidelity of existing integrations.
3. Turn warnings into recovery workflows: checkpoint, trim, re-anchor constraints, compact, and
   verify.
4. Build privacy-preserving benchmarks and a community adapter ecosystem.

The north-star outcome is not a prettier token meter. It is helping developers finish long,
complex agent sessions with fewer repeated steps, fewer forgotten constraints, and more confidence
in the result. The full strategy, principles, roadmap, and success measures are in
[VISION.md](VISION.md).

## Development

Context Lens currently uses only the Python standard library at runtime.

```bash
python3 test_analyzer.py
```

Expected output: `test_analyzer: ALL PASS`.

Contributions are welcome, especially host telemetry research, anonymized failure cases, adapter
design, documentation, and calibration work. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening
a pull request.

## Project

- [Vision and roadmap](VISION.md)
- [Manual test guide](MANUAL-TEST.md)
- [Changelog](CHANGELOG.md)
- [MIT License](LICENSE)

Built by [Edwin Hartarto](https://github.com/edwinidrus) as an open engineering project for the
AI developer-tools community.
