# Manual test — Context-Lens (all milestones)

Two lanes. **Offline** is fast and deterministic (no session restart) — proves the logic.
**Live** confirms the wiring inside Claude Code. Do the offline lane first.

Run everything from the plugin dir:

```bash
cd /path/to/Context-lens
```

Set your real transcript once (used by several checks):

```bash
find ~/.claude/projects -name '*.jsonl' -printf '%T@ %p\n' | sort -nr | head
T=/path/to/your/session.jsonl
```

Never commit a real transcript; it can contain prompts, source code, tool output, and local paths.

---

## 0. Offline suite (covers M1–M4 logic in one shot)

```bash
python3 test_analyzer.py        # expect: test_analyzer: ALL PASS
```

That's the fastest confidence check. The per-milestone sections below let you *see* each
surface.

---

## M1 — rot report

```bash
python3 scripts/analyzer.py --report --transcript "$T"
```

Expect: a header with the friendly model + raw id, `Rot score N/100 🟢/🟡/🔴 ZONE`, a
composition table, and a "Top dead weight" list. All four **Signals** (S1–S4) show numbers.

**Live:** `/context-lens` prints the same report.

---

## M2 — dashboard + statusline

Render the dashboard from your real session and open it:

```bash
python3 scripts/analyzer.py --html /tmp/context-lens.html --transcript "$T"
xdg-open file:///tmp/context-lens.html    # or paste the file:// URL into a browser
```

Expect: model header, context gauge %, rot dial, regime banner, composition donut, rot
sparkline. Dark/light follows your browser theme.

**Statusline:** render the line directly (simulating host JSON):

```bash
echo '{"context_window":{"used_percentage":44},"model":{"display_name":"Opus 4.8"},"session_id":"nope"}' \
  | python3 scripts/analyzer.py --line
```

Expect: `[Opus 4.8] ⚪ ████░░░░░░ 44%` (⚪/no zone until a Stop hook has cached state).

To enable it in Claude Code, add an absolute path to your user or project settings:

```json
{
  "statusLine": {
    "type": "command",
    "command": "/absolute/path/to/Context-lens/scripts/statusline.sh"
  }
}
```

**Open in the browser:** `--open` launches the live dashboard (WSL → Windows browser) and
prints the URL:

```bash
python3 scripts/analyzer.py --open --transcript "$T"
```

**Intra-turn refresh (PostToolUse):** the dashboard also updates after every tool call, not
only at turn end. Simulate two tool calls and confirm `report.html` is rewritten each time
while `r_history` does **not** grow (that stays one-per-turn):

```bash
SID=$(basename "$T" .jsonl)
before=$(python3 -c "import json;print(json.load(open('$HOME/.claude/context-lens/$SID/state.json'))['r_history'])" 2>/dev/null)
echo "{\"transcript_path\":\"$T\",\"session_id\":\"$SID\"}" | python3 scripts/analyzer.py --refresh
after=$(python3 -c "import json;print(json.load(open('$HOME/.claude/context-lens/$SID/state.json'))['r_history'])")
echo "r_history before=$before after=$after   (must be equal — refresh never appends)"
```

**Live:** after the statusLine settings line (README), the gauge shows in the status bar. In
a turn that makes several tool calls, watch the donut / dead-weight move *within* the turn.
The token gauge itself steps at turn end (usage lands in the transcript only then).

### All-session monitor

After `/reload-plugins`, start two Claude Code sessions in different project directories and run:

```text
/context-lens-monitor
```

The browser should open `~/.context-lens/all-sessions.html`. Confirm both sessions appear
with only project basename, shortened session ID, model, phase, health signals, score, and zone.
Send a prompt in one session and verify its card moves to `running`, then to `waiting` when the turn
ends. Trigger a permission notification if convenient and verify the card moves to **Needs
attention**. Exit one session and verify it appears under **Ended in the last 24 hours**; resume it
and verify it becomes active again.

Privacy check: inspect the generated `summary.json` files and `all-sessions.html`. They must not
contain prompt text, source excerpts, tool output, transcript paths, or full working-directory
paths. A running phase with no event for five minutes may show `update stale (estimate)`; this is
freshness labeling, not a claim that the Claude session ended.

### Codex adapter

Build and install a disposable local marketplace, then start a new Codex thread:

```bash
OUT=/tmp/context-lens-marketplace-$RANDOM
python3 scripts/build_codex_marketplace.py "$OUT"
codex plugin marketplace add "$OUT"
codex plugin add context-lens@context-lens-local
```

In the new thread, use `/hooks` to review and trust Context Lens. Use `/skills` to select
`context-lens:context-lens` (or type `$context-lens:context-lens`), submit a prompt that uses a tool,
and verify the session page progresses through `running` and `waiting` while its tool/turn counters
increase. Select `context-lens:context-lens-monitor` and confirm the Codex card shows the project
basename, `codex`, model, lifecycle phase, and `context and S1–S4 unavailable`.

Repeat from a newly launched opt-in process:

```bash
CONTEXT_LENS_EXPERIMENTAL_CODEX_TRANSCRIPT=1 codex
```

After a completed turn, confirm a compatible rollout shows a **PARTIAL** card, token gauge, and
experimental S1. Confirm S2–S4 and the combined rot score remain unavailable. If the installed
Codex build emits no compatible `token_count` record, confirm the card remains lifecycle-only with
a pending/unavailable note and no hook failure.

Inspect `~/.context-lens/<session-id>/summary.json` and confirm it contains no prompt, tool input,
tool response, transcript path, or full working-directory path. Permission prompts should move the
card to **Needs attention**. Since Codex has no documented `SessionEnd` event, the manual inactivity
check is time-based and explicitly labeled as an estimate.

---

## M3 — zone-crossing awareness (user + model channels)

```bash
python3 - <<'PY'
import importlib.util, json, tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location("a","scripts/analyzer.py")
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
td=tempfile.mkdtemp(); a.CACHE_ROOT=Path(td)
(a.session_dir("demo")/"state.json").write_text(json.dumps({"zone":"GREEN","r":10,"r_history":[10]}))
hot=Path(td)/"hot.jsonl"; big="x"*40000
hot.write_text("\n".join(json.dumps(r) for r in [
 {"type":"user","message":{"content":"do it"}},
 {"type":"assistant","message":{"model":"claude-opus-4-8","usage":{"input_tokens":200000},
   "content":[{"type":"tool_use","id":"1","name":"Read","input":{"file_path":"/x"}}]}},
 {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"1","content":big}]}},
 {"type":"assistant","message":{"model":"claude-opus-4-8","usage":{"input_tokens":200000},
   "content":[{"type":"tool_use","id":"2","name":"Read","input":{"file_path":"/x"}}]}},
 {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"2","content":big}]}}]))
out=a.update({"transcript_path":str(hot),"session_id":"demo"})
print("USER SEES (systemMessage):", out["systemMessage"])
print("MODEL SEES next turn:\n"+a.prompt_note({"session_id":"demo"})["hookSpecificOutput"]["additionalContext"])
print("delivered once -> second call:", a.prompt_note({"session_id":"demo"}))
PY
```

Expect: a `🟡`/`🔴` warning line for you, a ~90-token awareness note for the model, and
`None` on the second `prompt_note` (delivered once, then cleared).

**Live:** `/reload-plugins` (arms the UserPromptSubmit hook), then to watch the *user* channel
fire, seed the cached zone high and send any prompt:

```bash
SID=<your session_id>   # newest dir under ~/.claude/context-lens/
echo '{"zone":"RED","r":80,"r_history":[80]}' > ~/.claude/context-lens/$SID/state.json
```

Next turn shows a `context rot GREEN (R=…)` system line (a downward crossing). The model note
only queues on a *worsening* crossing, so the offline snippet above is the way to see it.

---

## M4 — compaction before/after loop

```bash
python3 - <<'PY'
import importlib.util, json, tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location("a","scripts/analyzer.py")
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
td=tempfile.mkdtemp(); a.CACHE_ROOT=Path(td); big="x"*40000
pre=Path(td)/"pre.jsonl"
pre.write_text("\n".join(json.dumps(r) for r in [
 {"type":"user","message":{"content":"go"}},
 {"type":"assistant","message":{"model":"claude-opus-4-8","usage":{"input_tokens":200000},
   "content":[{"type":"tool_use","id":"1","name":"Read","input":{"file_path":"/x"}}]}},
 {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"1","content":big}]}},
 {"type":"assistant","message":{"model":"claude-opus-4-8","usage":{"input_tokens":200000},
   "content":[{"type":"tool_use","id":"2","name":"Read","input":{"file_path":"/x"}}]}},
 {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"2","content":big}]}}]))
post=Path(td)/"post.jsonl"
post.write_text("\n".join(json.dumps(r) for r in [
 {"type":"user","message":{"content":"[summary]"}},
 {"type":"assistant","message":{"model":"claude-opus-4-8","usage":{"input_tokens":22000},
   "content":[{"type":"text","text":"ok"}]}}]))
a.precompact({"transcript_path":str(pre),"session_id":"c"})     # /compact about to run
out=a.update({"transcript_path":str(post),"session_id":"c"})     # first turn after
print("USER SEES:", out["systemMessage"])
print("MODEL SEES:", a.prompt_note({"session_id":"c"})["hookSpecificOutput"]["additionalContext"])
PY
```

Expect: `⚠ compaction: 200K → 22K (−178K). Dead weight cleared: 10K.` plus the FM4
lossy-summary caution for the model.

**Live:** after `/reload-plugins`, run `/compact`. On the **first turn after** compaction you
see the `⚠ compaction: … (−…K)` line. (Next turn, not instant — post-compaction token counts
only become real once the model takes a turn.)

---

## M5 — packaging / install

```bash
claude plugin validate .                                    # -> Validation passed
claude plugin marketplace add "$(pwd)"                       # -> Successfully added
claude plugin install context-lens@context-lens             # -> Successfully installed
# ... verify /context-lens works in a fresh session ...
claude plugin uninstall context-lens@context-lens           # clean up if you use the dev symlink
claude plugin marketplace remove context-lens
```

Validate and package the Codex plugin separately:

```bash
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
python3 scripts/build_codex_marketplace.py /tmp/context-lens-marketplace-validation
codex plugin marketplace add /tmp/context-lens-marketplace-validation
codex plugin add context-lens@context-lens-local
```

> Don't run the dev symlink **and** a marketplace install at once — hooks fire twice
> (doubled dashboard writes + warnings). Pick one (README "Install").

---

## Pass table

| Check | Pass condition |
|-------|----------------|
| Offline suite | `test_analyzer: ALL PASS` |
| M1 | report shows score, zone, S1–S4 numeric, dead-weight list |
| M2 | current dashboard renders; monitor follows two sessions; `--line` prints a gauge |
| M3 | systemMessage + ~90-token note; 2nd `prompt_note` is `None` |
| M4 | `⚠ compaction: … (−…K)` + FM4 caution |
| M5 | Claude and Codex validation passes; both marketplace installs succeed |
