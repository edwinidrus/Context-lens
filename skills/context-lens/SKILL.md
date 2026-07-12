---
name: context-lens
description: Show context-rot status for the current Claude Code session — how full the context is, whether quality is degrading (GREEN/AMBER/RED regime), what dead weight to clear, and a live dashboard. Trigger on "context lens", "context rot", "context usage", "how full is my context", "am I degrading", "/context-lens".
---

# Context-Lens

Report the current session's context-rot status.

On Claude Code, run the analyzer, print its report verbatim, then open the live dashboard:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/analyzer.py" --report
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/analyzer.py" --open
```

On Codex, open the current session's lifecycle report. Context-token and S1-S4 telemetry remain
explicitly unavailable because Codex hooks do not expose stable inputs for those signals:

```bash
python3 "${PLUGIN_ROOT}/scripts/analyzer.py" --open-current
```

`--open` renders the dashboard if needed, launches it in the user's browser (on WSL, the
Windows default browser), and prints the `file://…/report.html` URL. Show that URL to the
user as the fallback if their browser did not pop up.

The dashboard self-refreshes (~2s) and is rewritten after every tool call and at turn end,
so it tracks the session live. The headline token gauge steps at turn end (the model's token
usage only lands in the transcript then); composition, dead weight, and signals move within
the turn.

For a read-only combined view of local Claude Code and Codex sessions, use
`/context-lens-monitor`.
