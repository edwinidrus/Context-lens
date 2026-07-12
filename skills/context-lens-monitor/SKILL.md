---
name: context-lens-monitor
description: Open the local Context Lens command center for Claude Code and Codex sessions on this machine. Trigger on "context lens monitor", "all context lens sessions", "monitor my sessions", "session command center", "/context-lens-monitor".
---

# Context Lens Monitor

Open the local, read-only command center for every Context Lens-enabled Claude Code and Codex
session on this machine:

```bash
ROOT="${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}"
python3 "${ROOT}/scripts/analyzer.py" --open-all
```

Show the printed `file://…/all-sessions.html` URL to the user as a fallback if their browser did
not open. The page refreshes every two seconds and is regenerated from privacy-minimized session
summaries after supported lifecycle events. It never displays prompts, source code, tool output,
transcript paths, or full working-directory paths. Claude sessions show S1-S4 when available;
Codex sessions show lifecycle coverage and label context-health scores unavailable.
