# Manual test — Context-Lens (all milestones)

Two lanes. **Offline** is fast and deterministic (no session restart) — proves the logic.
**Live** confirms the wiring inside Claude Code. Do the offline lane first.

Run everything from the plugin dir:

```bash
cd ~/hobbys/claude_code_plugin/architect/context-lens
```

Set your real transcript once (used by several checks):

```bash
T=~/.claude/projects/-home-edwinidrus-hobbys-claude-code-plugin-architect/63630a11-a7f0-454a-a976-9a44dd06df8c.jsonl
```

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

> Don't run the dev symlink **and** a marketplace install at once — hooks fire twice
> (doubled dashboard writes + warnings). Pick one (README "Install").

---

## Pass table

| Check | Pass condition |
|-------|----------------|
| Offline suite | `test_analyzer: ALL PASS` |
| M1 | report shows score, zone, S1–S4 numeric, dead-weight list |
| M2 | dashboard renders all widgets; `--line` prints a gauge |
| M3 | systemMessage + ~90-token note; 2nd `prompt_note` is `None` |
| M4 | `⚠ compaction: … (−…K)` + FM4 caution |
| M5 | `validate` passes; `marketplace add` + `install` succeed |
