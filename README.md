# Context-Lens

A Claude Code plugin for visualizing **context rot** — detecting when an agent's answer quality starts degrading as its context window fills, long before the hard token limit.

Context-Lens reads live session telemetry, surfaces the four failure modes from [LOCA-bench](https://arxiv.org/html/2602.07962v1), and recommends mitigations at the right moment through three views:

- **Statusline** — always-on one-line glance
- **`/context-lens`** — on-demand terminal report
- **Live HTML dashboard** — auto-refreshing token gauge and health regime

The plugin is built and installable — see [`context-lens/`](context-lens/) (README, install,
changelog) and [`context-lens/MANUAL-TEST.md`](context-lens/MANUAL-TEST.md). The full design
and causality are in [`ARCHITECTURE.md`](ARCHITECTURE.md); the phase-by-phase build history
is in [`milestones/`](milestones/).
