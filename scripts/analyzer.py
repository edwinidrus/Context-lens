#!/usr/bin/env python3
"""context-lens analyzer — score context rot from a Claude Code transcript.

Signals map to LOCA-bench (arXiv 2602.07962v1) failure modes; see ARCHITECTURE.md §4.3.
Stdlib only: this runs inline from hooks/statusline and must stay fast and dep-free.
"""
import datetime
import json
import platform
import re
import statistics
import subprocess
import sys
import webbrowser
from pathlib import Path

# ponytail: full reparse each turn — measured 7.4ms/MB; revisit offset-resume only if
# transcripts hit ~50MB. state.json keeps only what a reparse can't recover.
CACHE_ROOT = Path.home() / ".claude" / "context-lens"
WINDOW = 200_000  # ponytail: knob — hook input carries no window size; 1M models exist

MODEL_NAMES = {
    "claude-opus-4-8": "Opus 4.8",
    "claude-fable-5": "Fable 5",
    "claude-sonnet-5": "Sonnet 5",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
}

# ponytail: calibration knobs, not constants — LOCA-bench thresholds shift per task type
S1_RAMP = [(0, 0), (32_000, 0), (96_000, 50), (128_000, 85), (160_000, 100)]
WEIGHTS = {"s1": 0.35, "s2": 0.25, "s3": 0.25, "s4": 0.15}  # s2/s4 land in M3


def est_tokens(obj):
    """Rough token estimate: chars/4. Proportions reliable, absolutes ±15% (ARCH §5)."""
    if isinstance(obj, str):
        return len(obj) // 4
    return len(json.dumps(obj, ensure_ascii=False)) // 4


def tool_target(name, tool_input):
    """Stable identity of what a tool call touched, for supersession grouping."""
    ti = tool_input or {}
    return ti.get("file_path") or ti.get("url") or ti.get("command") or json.dumps(ti, sort_keys=True)[:80]


def parse_transcript(path):
    comp = {"tool_results": 0, "assistant_text": 0, "thinking": 0, "user_text": 0}
    tool_uses = {}      # tool_use_id -> (tool_name, target)
    result_tokens = {}  # tool_use_id -> tokens of its result
    total = 0
    model = None
    running = 0         # est-token cursor over the whole transcript (for S4 distance)
    last_instr = 0      # cursor value at the last genuine user instruction
    turn_tools = []     # tool_use count per assistant turn (for S2 cadence)
    for line in open(path, encoding="utf-8"):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("isSidechain") or d.get("type") not in ("user", "assistant"):
            continue
        msg = d.get("message") or {}
        content = msg.get("content")
        if d["type"] == "assistant":
            u = msg.get("usage") or {}
            t = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                 + u.get("cache_read_input_tokens", 0))
            if t:
                total = t  # latest main-chain entry = live context (exact)
            if msg.get("model"):
                model = msg["model"]
            tcount = 0
            for b in content or []:
                bt = b.get("type")
                if bt == "text":
                    tk = est_tokens(b.get("text", ""))
                    comp["assistant_text"] += tk
                    running += tk
                elif bt == "thinking":
                    # note: Claude Code strips thinking text from transcripts (signature
                    # only), so this usually reads 0K — kept for transcripts that carry it
                    tk = est_tokens(b.get("thinking", ""))
                    comp["thinking"] += tk
                    running += tk
                elif bt == "tool_use":
                    tool_uses[b.get("id")] = (b.get("name", "?"), tool_target(b.get("name"), b.get("input")))
                    running += est_tokens(b.get("input"))
                    tcount += 1
            turn_tools.append(tcount)
        else:  # user
            if isinstance(content, str):
                tk = est_tokens(content)
                comp["user_text"] += tk
                running += tk
                last_instr = running  # human spoke -> constraints re-entered context
            else:
                for b in content or []:
                    if b.get("type") == "tool_result":
                        tk = est_tokens(b.get("content", ""))
                        comp["tool_results"] += tk
                        result_tokens[b.get("tool_use_id")] = tk
                        running += tk
                    elif b.get("type") == "text":
                        tk = est_tokens(b.get("text", ""))
                        comp["user_text"] += tk
                        running += tk
                        last_instr = running

    # supersession: same (tool, target) called again -> all but the last result are dead
    groups = {}
    for uid, key in tool_uses.items():
        groups.setdefault(key, []).append(uid)
    dead_tokens, dead_items, dup_reads = 0, [], 0
    for (tool, target), uids in groups.items():
        if len(uids) < 2:
            continue
        dup_reads += 1
        dead = sum(result_tokens.get(u, 0) for u in uids[:-1])
        dead_tokens += dead
        dead_items.append((dead, f"{tool} {target} x{len(uids)}"))
    dead_items.sort(reverse=True)
    return {"total": total, "model": model, "comp": comp,
            "dead_tokens": dead_tokens, "dead_items": dead_items[:3], "dup_reads": dup_reads,
            "instr_distance": running - last_instr, "turn_tools": turn_tools}


def s1_load(total):
    for (x0, y0), (x1, y1) in zip(S1_RAMP, S1_RAMP[1:]):
        if total <= x1:
            return round(y0 + (y1 - y0) * (total - x0) / (x1 - x0)) if total > x0 else y0
    return 100


def s2_exploration(turn_tools, s1):
    # paper failure mode 3: exploration plateaus at 96K. Signal = tool-call cadence
    # declining in recent turns vs earlier, gated by deep-context reach (s1).
    if len(turn_tools) < 4:
        return 0  # not enough turns to read a trend
    half = len(turn_tools) // 2
    early = statistics.median(turn_tools[:half])
    recent = statistics.median(turn_tools[half:])
    if early <= 0:
        return 0
    decline = max(0.0, (early - recent) / early)  # 0..1
    return round(decline * 100 * s1 / 100)


def s4_instr_distance(distance, s1):
    # paper failure mode 2: instruction-following weakens with distance from where
    # constraints last entered context. ~32K = notable onset; scaled by s1 per §4.3.
    raw = min(100, distance / 32_000 * 100)
    return round(raw * s1 / 100)


def s3_dead_weight(dead_tokens, total):
    # paper: clearing 50% of tool output = best mitigation -> 50% dead share scores 100
    share = dead_tokens / total * 100 if total else 0
    return min(100, round(share * 2))


def rot_score(sig):
    # ponytail: S2/S4 arrive in M3 — renormalize over the signals that exist
    live = {k: v for k, v in sig.items() if v is not None}
    w = sum(WEIGHTS[k] for k in live)
    return round(sum(WEIGHTS[k] * v for k, v in live.items()) / w) if w else 0


def zone(r):
    return "GREEN" if r < 40 else "AMBER" if r < 70 else "RED"


ZONE_ICON = {"GREEN": "\U0001f7e2", "AMBER": "\U0001f7e1", "RED": "\U0001f534"}
ZONE_ADVICE = {
    "GREEN": "Healthy regime. No action needed.",
    "AMBER": "Degradation measurable (past 32K onset). Batch remaining work; offload durable facts to files/memory.",
    "RED": "Plateau/collapse regime (96K+). /compact now, then re-state active constraints.",
}


ZONE_RANK = {"GREEN": 0, "AMBER": 1, "RED": 2}


def dead_pct(d):
    return round(d["dead_tokens"] / d["total"] * 100) if d["total"] else 0


def user_message(d):
    """One-line user-facing warning on a zone crossing (systemMessage)."""
    return (f"{ZONE_ICON[d['zone']]} context rot {d['zone']} (R={d['r']}): "
            f"{dead_pct(d)}% dead tool output, {d['total']/1000:.0f}K/{WINDOW//1000}K tokens")


def compaction_diff(pc, d):
    """Before/after story for a /compact (ARCHITECTURE §4.8). Returns (user_msg, model_note).

    ponytail: 'dead weight cleared' = pre_dead - post_dead. We can't know which exact tokens
    the summarizer dropped; the superseded-output delta is the honest, cheap proxy.
    """
    before, after = pc["total"], d["total"]
    cleared = before - after
    dead_cleared = max(0, pc.get("dead", 0) - d["dead_tokens"])
    msg = (f"⚠ compaction: {before/1000:.0f}K → {after/1000:.0f}K "
           f"(−{cleared/1000:.0f}K). Dead weight cleared: {dead_cleared/1000:.0f}K.")
    note = (msg + "\nSummaries are lossy (LOCA-bench FM4): verify critical facts against "
            "files, not memory of them.")
    return msg, note


def awareness_note(d):
    """~90-token model-facing context-awareness note (ARCHITECTURE §4.5)."""
    return (f"[context-lens] Context status: {d['zone']} (rot score {d['r']}/100).\n"
            f"Live context: {d['total']/1000:.0f}K/{WINDOW//1000}K tokens. "
            f"{dead_pct(d)}% is superseded tool output.\n"
            "Known effects at this level: exploration plateaus, early constraints fade.\n"
            "Recommended: batch remaining lookups into single Bash pipelines; "
            "persist durable findings to files/memory before continuing; "
            "re-read active constraints if the task depends on them.")


def friendly_model(mid):
    return MODEL_NAMES.get(mid, mid or "unknown")


def find_transcript():
    proj = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(Path.cwd()))
    files = sorted(proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        sys.exit(f"context-lens: no transcript found under {proj}")
    return files[-1]


def analyze(path):
    d = parse_transcript(path)
    d["s1"] = s1_load(d["total"])
    d["s2"] = s2_exploration(d["turn_tools"], d["s1"])
    d["s3"] = s3_dead_weight(d["dead_tokens"], d["total"])
    d["s4"] = s4_instr_distance(d["instr_distance"], d["s1"])
    d["r"] = rot_score({"s1": d["s1"], "s2": d["s2"], "s3": d["s3"], "s4": d["s4"]})
    d["zone"] = zone(d["r"])
    return d


def render_report(d, path):
    z, icon = d["zone"], ZONE_ICON[d["zone"]]
    total = d["total"]
    comp_total = sum(d["comp"].values()) or 1
    lines = [
        f"CONTEXT LENS - {Path(path).stem[:8]} - model {friendly_model(d['model'])} ({d['model']})",
        "=" * 60,
        f"Rot score  {d['r']}/100  {icon} {z}          window {total/1000:.1f}K tokens",
        "",
        "Composition (estimated)           Signals",
    ]
    labels = [("tool results", "tool_results"), ("assistant text", "assistant_text"),
              ("thinking", "thinking"), ("user + files", "user_text")]
    sigs = [f"S1 load          {d['s1']}", f"S2 exploration   {d['s2']}",
            f"S3 dead weight   {d['s3']}", f"S4 instr. dist.  {d['s4']}"]
    for (label, key), sig in zip(labels, sigs):
        v = d["comp"][key]
        pct = round(v / comp_total * 100)
        lines.append(f" {label:<14} {v/1000:6.1f}K {pct:3d}% {'#' * (pct // 10):<10} {sig}")
    lines.append(f"   superseded    {d['dead_tokens']/1000:6.1f}K  (dup call groups: {d['dup_reads']})")
    if d["dead_items"]:
        lines.append("")
        lines.append("Top dead weight (safe to lose in /compact)")
        for i, (tk, label) in enumerate(d["dead_items"], 1):
            lines.append(f" {i}. {label:<52} {tk/1000:5.1f}K")
    lines += ["", f"{icon} {ZONE_ADVICE[z]}"]
    return "\n".join(lines)


def session_dir(session_id):
    d = CACHE_ROOT / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_state(session_id):
    f = session_dir(session_id) / "state.json"
    try:
        return json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def write_dashboard(sid, a, st, r_history, path):
    """Single render path: persist the given state dict + rewrite report.html. Callers
    own the state (crossing flags, snapshots); this just stamps R/zone/history and writes."""
    st["r_history"] = r_history
    st["r"], st["zone"] = a["r"], a["zone"]
    sd = session_dir(sid)
    (sd / "state.json").write_text(json.dumps(st))
    (sd / "report.html").write_text(render_html(a, r_history, path))
    return sd / "report.html"


def update(hook):
    """Stop-hook entry: recompute, persist state, rewrite dashboard, and on a zone
    crossing warn the user (systemMessage) + queue a model-facing note for the next
    UserPromptSubmit. Returns hook stdout JSON (dict) or None.

    ponytail: the model-facing note is delivered at the NEXT prompt, not here —
    additionalContext at Stop is meant to *continue* the turn (docs), and we don't want
    a zone crossing to force an extra turn. Injecting at decision time is also when the
    model can act on it. See hooks.json (UserPromptSubmit) + prompt_note().
    """
    path = hook["transcript_path"]
    sid = hook.get("session_id") or Path(path).stem
    a = analyze(path)
    st = load_state(sid)
    prev_zone = st.get("zone")
    r_history = (st.get("r_history") or [])[-29:] + [a["r"]]   # one entry per completed turn

    out = None
    if prev_zone is not None and prev_zone != a["zone"]:
        out = {"systemMessage": user_message(a)}
        if ZONE_RANK[a["zone"]] > ZONE_RANK[prev_zone]:      # only worsening warrants
            st["pending_note"] = awareness_note(a)           # model context (it's costly)

    # compaction resolves here, not at SessionStart: the compacted transcript has no
    # assistant `usage` until this first post-compact turn, so `total` is only real now.
    pc = st.pop("pre_compact", None)                         # popped -> not persisted
    if pc and a["total"] < pc["total"]:
        msg, note = compaction_diff(pc, a)
        out = {"systemMessage": msg}          # supersedes any zone message this turn
        st["pending_note"] = note             # always: the lossy-summary caution matters

    write_dashboard(sid, a, st, r_history, path)
    return out


def refresh(hook):
    """PostToolUse entry: rewrite the dashboard mid-turn so composition/dead-weight/gauge
    move after every tool call — not only at turn end. NO r_history append and NO
    zone-crossing emit: those stay owned by the Stop hook (once per turn). No stdout.

    ponytail: mid-turn the live token TOTAL can't advance (assistant `usage` lands only at
    turn end); this moves everything else. Continuous total = a server, out of scope.
    """
    path = hook["transcript_path"]
    sid = hook.get("session_id") or Path(path).stem
    a = analyze(path)
    st = load_state(sid)                              # keep pending_note / pre_compact intact
    r_history = st.get("r_history") or [a["r"]]       # reuse existing; don't grow per tool call
    write_dashboard(sid, a, st, r_history, path)


def precompact(hook):
    """PreCompact entry (manual+auto): snapshot pre-compaction total + dead weight so the
    next Stop can report what /compact removed. No stdout."""
    path = hook["transcript_path"]
    sid = hook.get("session_id") or Path(path).stem
    a = analyze(path)
    st = load_state(sid)
    st["pre_compact"] = {"total": a["total"], "dead": a["dead_tokens"]}
    (session_dir(sid) / "state.json").write_text(json.dumps(st))


def prompt_note(hook):
    """UserPromptSubmit entry: deliver a queued awareness note once, then clear it."""
    sid = hook.get("session_id", "")
    st = load_state(sid)
    note = st.pop("pending_note", None)
    if not note:
        return None
    (session_dir(sid) / "state.json").write_text(json.dumps(st))
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": note}}


def line(host):
    """Statusline entry: render one gauge line from host JSON + cached state. O(1)."""
    cw = host.get("context_window") or {}
    pct = cw.get("used_percentage")
    pct = 0 if pct is None else round(pct)
    model = (host.get("model") or {}).get("display_name", "?")
    st = load_state(host.get("session_id", ""))
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    rot = f" · R{st['r']} {st['zone']}" if "r" in st else ""
    icon = ZONE_ICON.get(st.get("zone"), "⚪")
    return f"[{model}] {icon} {bar} {pct}%{rot}"


def render_html(d, r_history, path):
    """Self-contained live dashboard: no JS, no CDN; meta-refresh keeps it current.

    Colors are the dataviz reference palette (pre-validated, light+dark): status
    palette for zones, categorical slots for the donut, ink/surface tokens for text.
    """
    z = d["zone"]
    zone_color = {"GREEN": "var(--good)", "AMBER": "var(--warning)", "RED": "var(--critical)"}[z]
    total, comp = d["total"], d["comp"]
    pct = min(100, round(total / WINDOW * 100))
    comp_total = sum(comp.values()) or 1
    cats = [("tool results", comp["tool_results"], "var(--s1)"),
            ("assistant", comp["assistant_text"], "var(--s2)"),
            ("thinking", comp["thinking"], "var(--s3)"),
            ("user + files", comp["user_text"], "var(--s5)")]

    # donut: stacked stroke arcs on pathLength=100 circles, 1-unit gap between segments
    arcs, legend, offset = [], [], 25  # start at 12 o'clock
    for label, v, color in cats:
        seg = v / comp_total * 100
        draw = max(seg - 1, 0)
        arcs.append(
            f'<circle r="15.9" cx="21" cy="21" fill="none" stroke="{color}" stroke-width="6" '
            f'pathLength="100" stroke-dasharray="{draw:.2f} {100 - draw:.2f}" '
            f'stroke-dashoffset="{offset:.2f}"><title>{label}: {v/1000:.1f}K ({seg:.0f}%)</title></circle>')
        legend.append(f'<div class="lg"><i style="background:{color}"></i>{label}'
                      f'<b>{v/1000:.1f}K · {seg:.0f}%</b></div>')
        offset -= seg
    dead_pct = round(d["dead_tokens"] / total * 100) if total else 0

    # sparkline: R (0-100) over last turns, single series -> no legend needed
    h = r_history or [d["r"]]
    n = max(len(h) - 1, 1)
    pts = " ".join(f"{i / n * 100:.1f},{40 - v * 0.4:.1f}" for i, v in enumerate(h))
    dots = "".join(f'<circle cx="{i / n * 100:.1f}" cy="{40 - v * 0.4:.1f}" r="1.6" fill="var(--s1)">'
                   f'<title>turn {i - len(h) + 1}: R{v}</title></circle>' for i, v in enumerate(h))

    now = datetime.datetime.now().strftime("%H:%M:%S")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="2"><title>Context-Lens</title><style>
:root {{ --surface:#fcfcfb; --plane:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --good:#0ca30c; --warning:#fab219; --critical:#d03b3b;
  --s1:#2a78d6; --s2:#1baf7a; --s3:#eda100; --s5:#4a3aa7; }}
@media (prefers-color-scheme: dark) {{
:root {{ --surface:#1a1a19; --plane:#0d0d0d; --ink:#ffffff; --ink2:#c3c2b7;
  --grid:#2c2c2a; --s1:#3987e5; --s2:#199e70; --s3:#c98500; --s5:#9085e9; }} }}
* {{ box-sizing:border-box; margin:0 }}
body {{ font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; background:var(--plane);
  color:var(--ink); padding:24px; max-width:720px; margin:auto }}
.card {{ background:var(--surface); border:1px solid var(--grid); border-radius:8px;
  padding:16px 20px; margin-bottom:12px }}
h1 {{ font-size:16px }} .sub {{ color:var(--muted); font-size:12px }}
.row {{ display:flex; gap:12px; flex-wrap:wrap }} .row .card {{ flex:1; min-width:200px }}
.hero {{ font-size:44px; font-weight:700 }}
.gauge {{ height:14px; background:var(--grid); border-radius:7px; overflow:hidden; margin:8px 0 4px }}
.gauge i {{ display:block; height:100%; border-radius:7px 0 0 7px }}
.banner {{ border-left:4px solid; padding:10px 14px }}
.lg {{ display:flex; align-items:center; gap:8px; font-size:13px; color:var(--ink2); margin:3px 0 }}
.lg i {{ width:10px; height:10px; border-radius:2px; flex:none }}
.lg b {{ margin-left:auto; color:var(--ink); font-weight:600; font-variant-numeric:tabular-nums }}
svg {{ display:block }}</style></head><body>
<div class="card"><h1>Context-Lens <span class="sub">⟳ live · {now}</span></h1>
<div>Model: <b>{friendly_model(d["model"])}</b> <span class="sub">({d["model"]})</span>
<span class="sub" style="float:right">session {Path(path).stem[:8]}</span></div></div>
<div class="card banner" style="border-color:{zone_color}">
<b style="color:{zone_color}">{ZONE_ICON[z]} {z}</b> — {ZONE_ADVICE[z]}</div>
<div class="row">
<div class="card"><div class="sub">CONTEXT WINDOW</div><div class="hero">{pct}%</div>
<div class="gauge"><i style="width:{pct}%;background:{zone_color}"></i></div>
<div class="sub">{total/1000:.1f}K / {WINDOW//1000}K tokens · dead weight {dead_pct}%</div></div>
<div class="card"><div class="sub">ROT SCORE</div>
<div class="hero" style="color:{zone_color}">{d["r"]}</div>
<div class="sub">of 100 · S1 load {d["s1"]} · S3 dead {d["s3"]}</div></div>
</div>
<div class="row">
<div class="card"><div class="sub">COMPOSITION (estimated)</div>
<div style="display:flex;gap:16px;align-items:center;margin-top:8px">
<svg width="120" height="120" viewBox="0 0 42 42" style="transform:rotate(0)">{"".join(arcs)}</svg>
<div style="flex:1">{"".join(legend)}</div></div></div>
<div class="card"><div class="sub">ROT TREND (last {len(h)} turns)</div>
<svg width="100%" height="90" viewBox="0 0 100 44" preserveAspectRatio="none" style="margin-top:8px">
<line x1="0" y1="24" x2="100" y2="24" stroke="var(--grid)" stroke-width="0.5"/>
<line x1="0" y1="12" x2="100" y2="12" stroke="var(--grid)" stroke-width="0.5"/>
<polyline points="{pts}" fill="none" stroke="var(--s1)" stroke-width="1.2"/>{dots}</svg>
<div class="sub">gridlines: R40 (AMBER), R70 (RED)</div></div>
</div></body></html>"""


def find_report(path=None):
    """Resolve the live report.html for the current session, rendering it if the Stop hook
    hasn't written one yet (first /context-lens of a session)."""
    path = path or find_transcript()
    sid = Path(path).stem
    html = session_dir(sid) / "report.html"
    if not html.exists():
        a = analyze(path)
        st = load_state(sid)
        write_dashboard(sid, a, st, st.get("r_history") or [a["r"]], path)
    return html


def open_browser(html):
    """Open the dashboard in the user's real browser. WSL has no display browser the user
    watches — hand the file to the Windows default browser via a wslpath-translated path.
    Never let a failed launch break /context-lens: swallow errors, the caller prints the URL.
    """
    try:
        if "microsoft" in platform.uname().release.lower():  # WSL -> Windows browser
            # ponytail: no wslview on this box; cmd.exe start is always present under WSL
            win = subprocess.check_output(["wslpath", "-w", str(html)], text=True).strip()
            subprocess.run(["cmd.exe", "/c", "start", "", win], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        return webbrowser.open(html.as_uri())                # macOS / native Linux
    except Exception:
        return False


def main(argv):
    path = None
    if "--transcript" in argv:
        path = argv[argv.index("--transcript") + 1]
    if "--report" in argv:
        path = path or find_transcript()
        print(render_report(analyze(path), path))
    elif "--update" in argv:
        out = update(json.load(sys.stdin))
        if out:
            print(json.dumps(out))
    elif "--refresh" in argv:
        refresh(json.load(sys.stdin))
    elif "--open" in argv:
        html = find_report(path)
        open_browser(html)
        print(html.as_uri())
    elif "--prompt-note" in argv:
        out = prompt_note(json.load(sys.stdin))
        if out:
            print(json.dumps(out))
    elif "--precompact" in argv:
        precompact(json.load(sys.stdin))
    elif "--line" in argv:
        print(line(json.load(sys.stdin)))
    elif "--html" in argv:
        out = Path(argv[argv.index("--html") + 1])
        path = path or find_transcript()
        d = analyze(path)
        out.write_text(render_html(d, [d["r"]], path))
        print(out)
    else:
        sys.exit("usage: analyzer.py --report|--update|--refresh|--line|--open|"
                 "--html OUT [--transcript PATH]")


if __name__ == "__main__":
    main(sys.argv[1:])
