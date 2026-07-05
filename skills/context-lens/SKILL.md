---
name: context-lens
description: Show context-rot status for the current Claude Code session — how full the context is, whether quality is degrading (GREEN/AMBER/RED regime), what dead weight to clear, and a live dashboard. Trigger on "context lens", "context rot", "context usage", "how full is my context", "am I degrading", "/context-lens".
---

# Context-Lens

Report the current session's context-rot status.

Run the analyzer, print its report verbatim, then open the live dashboard in the browser:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/analyzer.py" --report
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/analyzer.py" --open
```

`--open` renders the dashboard if needed, launches it in the user's browser (on WSL, the
Windows default browser), and prints the `file://…/report.html` URL. Show that URL to the
user as the fallback if their browser did not pop up.

The dashboard self-refreshes (~2s) and is rewritten after every tool call and at turn end,
so it tracks the session live. The headline token gauge steps at turn end (the model's token
usage only lands in the transcript then); composition, dead weight, and signals move within
the turn.
