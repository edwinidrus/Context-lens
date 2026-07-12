#!/usr/bin/env python3
"""context-lens analyzer — score context rot from a Claude Code transcript.

Signals map to LOCA-bench (arXiv 2602.07962v1) failure modes; see ARCHITECTURE.md §4.3.
Stdlib only: this runs inline from hooks/statusline and must stay fast and dep-free.
"""
import datetime
import html
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# ponytail: full Claude transcript reparse each turn — measured 7.4ms/MB; revisit
# offset-resume only if transcripts hit ~50MB. The opt-in Codex adapter reads a bounded
# rollout tail and extracts numeric token_count records only; that source is experimental.
DEFAULT_CACHE_ROOT = Path.home() / ".context-lens"
LEGACY_CLAUDE_CACHE_ROOT = Path.home() / ".claude" / "context-lens"
CACHE_ROOT = Path(os.environ.get("CONTEXT_LENS_CACHE_ROOT", DEFAULT_CACHE_ROOT))
DEFAULT_CONTEXT_WINDOW = 200_000
# Backward-compatible calibration alias. Rendering and summaries use the per-session
# value returned by detect_context_window(), never this value as a model catalogue.
WINDOW = DEFAULT_CONTEXT_WINDOW
SUMMARY_SCHEMA = "context-lens.session-summary.v1"
LEGACY_SUMMARY_SCHEMA = "context-lens.claude-session-summary.v1"
RECENT_ENDED_SECONDS = 24 * 60 * 60
RECENT_ENDED_LIMIT = 20
STALE_RUNNING_SECONDS = 5 * 60  # display-only estimate; never treated as SessionEnd
CODEX_INACTIVE_SECONDS = 30 * 60  # no SessionEnd hook exists; UI-only estimate
CODEX_EXPERIMENTAL_ENV = "CONTEXT_LENS_EXPERIMENTAL_CODEX_TRANSCRIPT"
CODEX_ROLLOUT_TAIL_BYTES = 8 * 1024 * 1024
CODEX_OBSERVATION_KEYS = {
    "context_tokens", "context_window_tokens", "context_window_source",
    "context_window_exact", "context_telemetry_confidence", "context_observed_at",
    "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
}

# ponytail: calibration knobs, not constants — LOCA-bench thresholds shift per task type
S1_RAMP = [(0, 0), (32_000, 0), (96_000, 50), (128_000, 85), (160_000, 100)]
WEIGHTS = {"s1": 0.35, "s2": 0.25, "s3": 0.25, "s4": 0.15}  # s2/s4 land in M3


def est_tokens(obj):
    """Rough token estimate: chars/4. Proportions reliable, absolutes ±15% (ARCH §5)."""
    if isinstance(obj, str):
        return len(obj) // 4
    return len(json.dumps(obj, ensure_ascii=False)) // 4


def model_id(value):
    """Return a provider-neutral model identifier from common runtime shapes."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("id", "model_id", "name", "display_name"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found.strip()
    return None


def _positive_int(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def _nonnegative_int(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= 0 else None


def codex_experimental_enabled():
    return os.environ.get(CODEX_EXPERIMENTAL_ENV, "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def codex_token_observation(hook):
    """Extract only numeric token metadata from the bounded tail of a Codex rollout.

    Codex documents transcript_path but explicitly does not stabilize the transcript
    schema. This parser is therefore opt-in, best-effort, content-blind, and fail-open:
    schema drift returns None so lifecycle monitoring keeps working.
    """
    if not codex_experimental_enabled() or not isinstance(hook, dict):
        return None
    raw_path = hook.get("transcript_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    try:
        path = Path(raw_path)
        size = path.stat().st_size
        start = max(0, size - CODEX_ROLLOUT_TAIL_BYTES)
        with path.open("rb") as stream:
            stream.seek(start)
            rows = stream.read().splitlines()
        if start and rows:
            rows = rows[1:]  # the first row may begin in the middle of a JSON object
    except OSError:
        return None

    for raw in reversed(rows):
        try:
            item = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        payload = item.get("payload") if item.get("type") == "event_msg" else None
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        latest = info.get("last_token_usage") if isinstance(info, dict) else None
        if not isinstance(latest, dict):
            continue
        total = _positive_int(latest.get("total_tokens"))
        window = _positive_int(info.get("model_context_window"))
        if not total or not window:
            continue
        observation = {
            "context_tokens": total,
            "context_window_tokens": window,
            "context_window_source": "Codex rollout token_count (experimental)",
            "context_window_exact": True,
            "context_telemetry_confidence": "experimental; transcript schema is unstable",
        }
        if isinstance(item.get("timestamp"), str):
            observation["context_observed_at"] = item["timestamp"]
        for source_key, target_key in (
                ("input_tokens", "input_tokens"),
                ("cached_input_tokens", "cached_input_tokens"),
                ("output_tokens", "output_tokens"),
                ("reasoning_output_tokens", "reasoning_output_tokens")):
            value = _nonnegative_int(latest.get(source_key))
            if value is not None:
                observation[target_key] = value
        return observation
    return None


def detect_context_window(*objects):
    """Detect an explicitly advertised context capacity without a model-name table.

    Providers and local runtimes use different model IDs, and open-weight servers can
    configure different limits for the same weights. Only explicit metadata is treated
    as exact; CONTEXT_LENS_CONTEXT_WINDOW is the local, deployment-specific override.
    """
    configured = _positive_int(os.environ.get("CONTEXT_LENS_CONTEXT_WINDOW"))
    if configured:
        return configured, "environment override", True

    scalar_keys = {
        "context_window_tokens", "contextWindowTokens", "context_window_size",
        "contextWindowSize", "max_context_tokens", "maxContextTokens",
        "context_length", "contextLength", "n_ctx",
    }
    container_keys = {"context_window", "contextWindow"}
    nested_keys = {"metadata", "model", "capabilities", "config", "configuration", "limits", "usage"}
    inner_keys = ("tokens", "size", "max_tokens", "maxTokens", "total_tokens", "totalTokens")

    def visit(value):
        if not isinstance(value, dict):
            return None
        for key in scalar_keys:
            found = _positive_int(value.get(key))
            if found:
                return found
        for key in container_keys:
            item = value.get(key)
            found = _positive_int(item)
            if found:
                return found
            if isinstance(item, dict):
                for inner in inner_keys:
                    found = _positive_int(item.get(inner))
                    if found:
                        return found
                found = visit(item)
                if found:
                    return found
        for key in nested_keys:
            found = visit(value.get(key))
            if found:
                return found
        return None

    for obj in objects:
        found = visit(obj)
        if found:
            return found, "runtime metadata", True
    return DEFAULT_CONTEXT_WINDOW, "default estimate", False


def format_tokens(tokens):
    return f"{tokens / 1_000_000:g}M" if tokens >= 1_000_000 else f"{tokens / 1000:g}K"


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
    context_window = None
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
        advertised_window, _, exact_window = detect_context_window(d, msg)
        if exact_window:
            context_window = advertised_window
        content = msg.get("content")
        if d["type"] == "assistant":
            u = msg.get("usage") or {}
            t = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                 + u.get("cache_read_input_tokens", 0))
            if t:
                total = t  # latest main-chain entry = live context (exact)
            detected_model = model_id(msg.get("model")) or model_id(d.get("model"))
            if detected_model:
                model = detected_model
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
    return {"total": total, "model": model, "context_window": context_window, "comp": comp,
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
            f"{dead_pct(d)}% dead tool output, {d['total']/1000:.0f}K/"
            f"{format_tokens(d['context_window'])} tokens")


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
            f"Live context: {d['total']/1000:.0f}K/{format_tokens(d['context_window'])} tokens. "
            f"{dead_pct(d)}% is superseded tool output.\n"
            "Known effects at this level: exploration plateaus, early constraints fade.\n"
            "Recommended: batch remaining lookups into single Bash pipelines; "
            "persist durable findings to files/memory before continuing; "
            "re-read active constraints if the task depends on them.")


def friendly_model(mid):
    """Create a readable label for any provider or open-weight model ID."""
    mid = model_id(mid)
    if not mid:
        return "unknown"
    words = [word for word in re.split(r"[/_: -]+", mid) if word]
    rendered = []
    for word in words:
        if word.isdigit() and rendered and re.fullmatch(r"\d+(?:\.\d+)*", rendered[-1]):
            rendered[-1] += "." + word
        elif re.fullmatch(r"\d+[bBkKmM]", word):
            rendered.append(word[:-1] + word[-1].upper())
        elif word.lower() in {"ai", "gpt", "llm"}:
            rendered.append(word.upper())
        else:
            rendered.append(word[:1].upper() + word[1:])
    return " ".join(rendered)


def find_transcript():
    proj = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(Path.cwd()))
    files = sorted(proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        sys.exit(f"context-lens: no transcript found under {proj}")
    return files[-1]


def analyze(path, runtime=None):
    d = parse_transcript(path)
    runtime_model = model_id((runtime or {}).get("model")) if isinstance(runtime, dict) else None
    if runtime_model and not d["model"]:
        d["model"] = runtime_model
    window, source, exact = detect_context_window(runtime, {"context_window_tokens": d["context_window"]})
    d["context_window"] = window
    d["context_window_source"] = source
    d["context_window_exact"] = exact
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
        # Preserve the v1.x Claude experience after moving new multi-host state to a
        # neutral root. Tests/custom roots never consult a real user's legacy cache.
        if CACHE_ROOT == DEFAULT_CACHE_ROOT:
            try:
                return json.loads((LEGACY_CLAUDE_CACHE_ROOT / session_id / "state.json").read_text())
            except (OSError, json.JSONDecodeError):
                pass
        return {}


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def atomic_write(path, text):
    """Replace a cache artifact atomically so browsers and parallel hooks never see
    a partially written JSON/HTML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def valid_summary(d):
    return (isinstance(d, dict) and d.get("schema") in (SUMMARY_SCHEMA, LEGACY_SUMMARY_SCHEMA)
            and all(isinstance(d.get(k, {}), dict)
                    for k in ("identity", "lifecycle", "observations", "signals", "health")))


def load_summary(session_id):
    f = session_dir(session_id) / "summary.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return d if valid_summary(d) else {}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def hook_host(hook):
    """Capability detection belongs at the adapter edge, not in scoring/rendering."""
    if hook.get("_context_lens_host") in ("claude-code", "codex"):
        return hook["_context_lens_host"]
    if os.environ.get("PLUGIN_ROOT") or hook.get("turn_id"):
        return "codex"
    model = str(hook.get("model") or "")
    return "claude-code" if model.startswith("claude-") else "codex" if model else "claude-code"


def summary_from_event(hook, phase, analysis=None, lifecycle="active", end_reason=None,
                       codex_observation=None):
    """Create the privacy-minimized monitor record. Raw observations and derived
    scores are deliberately separate; transcript text, tool targets, and full paths
    never enter this file."""
    sid = hook.get("session_id") or Path(hook.get("transcript_path", "unknown")).stem
    previous = load_summary(sid)
    host = hook_host(hook)
    now = utc_now()
    cwd = hook.get("cwd")
    identity = dict(previous.get("identity") or {})
    identity.update({
        "host": host,
        "session_id": sid,
        "project": Path(cwd).name if cwd else identity.get("project", "unknown"),
    })
    model = (analysis or {}).get("model") or hook.get("model") or identity.get("model")
    identity["model"] = model

    life = dict(previous.get("lifecycle") or {})
    life.update({
        "status": lifecycle,
        "phase": phase,
        "last_event": hook.get("hook_event_name", phase),
        "last_event_at": now,
    })
    life.setdefault("started_at", now)
    if lifecycle == "ended":
        life["ended_at"] = now
        life["end_reason"] = end_reason or hook.get("reason", "unknown")
    else:  # a resumed session becomes active again
        life["ended_at"] = None
        life["end_reason"] = None

    observations = dict(previous.get("observations") or {})
    signals = dict(previous.get("signals") or {})
    health = dict(previous.get("health") or {})
    coverage = dict(previous.get("coverage") or {})
    if analysis:
        observations = {
            "context_tokens": analysis["total"],
            "context_window_tokens": analysis["context_window"],
            "context_window_source": analysis["context_window_source"],
            "context_window_exact": analysis["context_window_exact"],
            "composition_estimated_tokens": analysis["comp"],
            "dead_weight_estimated_tokens": analysis["dead_tokens"],
            "dead_weight_percent": dead_pct(analysis),
            "instruction_distance_estimated_tokens": analysis["instr_distance"],
            "tool_calls_per_turn": analysis["turn_tools"],
            "estimate_note": "Character-based token observations are estimates (about +/-15%).",
        }
        signals = {
            "s1_load": analysis["s1"],
            "s2_exploration": analysis["s2"],
            "s3_dead_weight": analysis["s3"],
            "s4_instruction_distance": analysis["s4"],
            "experimental": True,
        }
        health = {"rot_score": analysis["r"], "zone": analysis["zone"]}
        coverage = {
            "lifecycle": "available",
            "context_tokens": "available",
            "signals": "available (S2-S4 include estimates)",
            "session_end": "available",
        }
    elif host == "codex":
        # Stable hooks provide lifecycle metadata only. An explicit opt-in may add a
        # content-blind numeric observation from the unstable rollout schema.
        observations.setdefault("tool_events", 0)
        observations.setdefault("turns_completed", 0)
        observations.setdefault("compactions_observed", 0)
        health = {}
        if codex_experimental_enabled():
            if codex_observation:
                observations.update(codex_observation)
            total = _positive_int(observations.get("context_tokens"))
            window = _positive_int(observations.get("context_window_tokens"))
            if total and window and observations.get("context_window_source"):
                signals = {
                    "s1_load": s1_load(total),
                    "s2_exploration": None,
                    "s3_dead_weight": None,
                    "s4_instruction_distance": None,
                    "experimental": True,
                }
                coverage = {
                    "lifecycle": "available (no SessionEnd event)",
                    "context_tokens": "experimental (Codex rollout token_count)",
                    "signals": "partial (experimental S1 only; S2-S4 unavailable)",
                    "session_end": "unavailable; inactivity is estimated from freshness",
                    "note": ("Context usage and S1 come from an opt-in numeric rollout record; "
                             "the Codex transcript schema is not stable."),
                }
            else:
                signals = {}
                coverage = {
                    "lifecycle": "available (no SessionEnd event)",
                    "context_tokens": "pending experimental token_count observation",
                    "signals": "pending experimental S1 observation",
                    "session_end": "unavailable; inactivity is estimated from freshness",
                    "note": "No compatible Codex token_count record was found in the rollout tail.",
                }
        else:
            for key in CODEX_OBSERVATION_KEYS:
                observations.pop(key, None)
            signals = {}
            coverage = {
                "lifecycle": "available (no SessionEnd event)",
                "context_tokens": "unavailable",
                "signals": "unavailable",
                "session_end": "unavailable; inactivity is estimated from freshness",
                "note": "Codex hook telemetry does not expose stable context-token or S1-S4 inputs.",
            }
    else:
        coverage.setdefault("lifecycle", "available")
        coverage.setdefault("context_tokens", "pending first analyzed event")
        coverage.setdefault("signals", "pending first analyzed event")
        coverage.setdefault("session_end", "available")

    return {
        "schema": SUMMARY_SCHEMA,
        "identity": identity,
        "lifecycle": life,
        "observations": observations,
        "signals": signals,
        "health": health,
        "coverage": coverage,
    }


def track_event(hook, phase, analysis=None, lifecycle="active", end_reason=None, increments=None):
    """Persist one session summary and best-effort refresh the shared monitor."""
    sid = hook.get("session_id") or Path(hook.get("transcript_path", "unknown")).stem
    observation = codex_token_observation(hook) if hook_host(hook) == "codex" else None
    summary = summary_from_event(hook, phase, analysis, lifecycle, end_reason, observation)
    for key, amount in (increments or {}).items():
        current = summary["observations"].get(key, 0)
        summary["observations"][key] = (current if isinstance(current, int) else 0) + amount
    atomic_write(session_dir(sid) / "summary.json", json.dumps(summary, indent=2))
    if summary["identity"].get("host") == "codex":
        atomic_write(session_dir(sid) / "report.html", render_codex_report(summary))
    try:
        write_overview()
    except OSError:
        # The session hook is more important than the derived shared surface. A later
        # event or --open-all regenerates the monitor from the durable summaries.
        pass
    return summary


def write_dashboard(sid, a, st, r_history, path):
    """Single render path: persist the given state dict + rewrite report.html. Callers
    own the state (crossing flags, snapshots); this just stamps R/zone/history and writes."""
    apply_session_window(a, st)
    st["r_history"] = r_history
    st["r"], st["zone"] = a["r"], a["zone"]
    sd = session_dir(sid)
    atomic_write(sd / "state.json", json.dumps(st))
    atomic_write(sd / "report.html", render_html(a, r_history, path))
    return sd / "report.html"


def apply_session_window(analysis, state):
    """Reuse exact capacity observed by another hook surface for this session."""
    if not analysis.get("context_window_exact") and state.get("context_window_exact"):
        window = _positive_int(state.get("context_window"))
        if window:
            analysis["context_window"] = window
            analysis["context_window_source"] = state.get("context_window_source", "runtime metadata")
            analysis["context_window_exact"] = True


def update(hook):
    """Stop-hook entry: recompute, persist state, rewrite dashboard, and on a zone
    crossing warn the user (systemMessage) + queue a model-facing note for the next
    UserPromptSubmit. Returns hook stdout JSON (dict) or None.

    ponytail: the model-facing note is delivered at the NEXT prompt, not here —
    additionalContext at Stop is meant to *continue* the turn (docs), and we don't want
    a zone crossing to force an extra turn. Injecting at decision time is also when the
    model can act on it. See hooks.json (UserPromptSubmit) + prompt_note().
    """
    if hook_host(hook) == "codex":
        track_event(hook, "waiting", increments={"turns_completed": 1})
        return None
    path = hook["transcript_path"]
    sid = hook.get("session_id") or Path(path).stem
    a = analyze(path, hook)
    st = load_state(sid)
    apply_session_window(a, st)
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
    track_event(hook, "waiting", a)
    return out


def refresh(hook):
    """PostToolUse entry: rewrite the dashboard mid-turn so composition/dead-weight/gauge
    move after every tool call — not only at turn end. NO r_history append and NO
    zone-crossing emit: those stay owned by the Stop hook (once per turn). No stdout.

    ponytail: mid-turn the live token TOTAL can't advance (assistant `usage` lands only at
    turn end); this moves everything else. Continuous total = a server, out of scope.
    """
    if hook_host(hook) == "codex":
        track_event(hook, "running", increments={"tool_events": 1})
        return
    path = hook["transcript_path"]
    sid = hook.get("session_id") or Path(path).stem
    a = analyze(path, hook)
    st = load_state(sid)                              # keep pending_note / pre_compact intact
    r_history = st.get("r_history") or [a["r"]]       # reuse existing; don't grow per tool call
    write_dashboard(sid, a, st, r_history, path)
    track_event(hook, "running", a)


def precompact(hook):
    """PreCompact entry (manual+auto): snapshot pre-compaction total + dead weight so the
    next Stop can report what /compact removed. No stdout."""
    if hook_host(hook) == "codex":
        track_event(hook, "compacting")
        return
    path = hook["transcript_path"]
    sid = hook.get("session_id") or Path(path).stem
    a = analyze(path, hook)
    st = load_state(sid)
    apply_session_window(a, st)
    st["pre_compact"] = {"total": a["total"], "dead": a["dead_tokens"]}
    atomic_write(session_dir(sid) / "state.json", json.dumps(st))
    track_event(hook, "compacting", a)


def prompt_note(hook):
    """UserPromptSubmit entry: deliver a queued awareness note once, then clear it."""
    if hook_host(hook) == "codex":
        track_event(hook, "running")
        return None
    sid = hook.get("session_id", "")
    st = load_state(sid)
    note = st.pop("pending_note", None)
    track_event(hook, "running")
    if not note:
        return None
    atomic_write(session_dir(sid) / "state.json", json.dumps(st))
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": note}}


def session_start(hook):
    track_event(hook, "ready")


def session_end(hook):
    track_event(hook, "ended", lifecycle="ended", end_reason=hook.get("reason"))


def notification(hook):
    ntype = hook.get("notification_type", "notification")
    if ntype in ("permission_prompt", "elicitation_dialog"):
        phase = "needs_attention"
    elif ntype == "idle_prompt":
        phase = "waiting"
    else:
        phase = (load_summary(hook.get("session_id", "")).get("lifecycle") or {}).get("phase", "ready")
    track_event(hook, phase)


def permission_request(hook):
    track_event(hook, "needs_attention")


def postcompact(hook):
    increments = {"compactions_observed": 1} if hook_host(hook) == "codex" else None
    track_event(hook, "running", increments=increments)


def line(host):
    """Statusline entry: render one gauge line from host JSON + cached state. O(1)."""
    cw = host.get("context_window") or {}
    pct = cw.get("used_percentage")
    pct = 0 if pct is None else round(pct)
    model = (host.get("model") or {}).get("display_name", "?")
    sid = host.get("session_id", "")
    st = load_state(sid)
    window, source, exact = detect_context_window(host)
    if sid and exact:
        st.update({"context_window": window, "context_window_source": source,
                   "context_window_exact": True})
        atomic_write(session_dir(sid) / "state.json", json.dumps(st))
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
    window = d["context_window"]
    pct = min(100, round(total / window * 100))
    window_note = "" if d["context_window_exact"] else " · capacity estimated"
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
svg {{ display:block }} a {{ color:var(--s1) }}</style></head><body>
<div class="card"><h1>Context-Lens <span class="sub">⟳ live · {now}</span></h1>
<div>Model: <b>{friendly_model(d["model"])}</b> <span class="sub">({d["model"]})</span>
<span class="sub" style="float:right">session {Path(path).stem[:8]} · <a href="../all-sessions.html">all sessions</a></span></div></div>
<div class="card banner" style="border-color:{zone_color}">
<b style="color:{zone_color}">{ZONE_ICON[z]} {z}</b> — {ZONE_ADVICE[z]}</div>
<div class="row">
<div class="card"><div class="sub">CONTEXT WINDOW</div><div class="hero">{pct}%</div>
<div class="gauge"><i style="width:{pct}%;background:{zone_color}"></i></div>
<div class="sub">{total/1000:.1f}K / {format_tokens(window)} tokens{window_note} · dead weight {dead_pct}%</div></div>
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


def render_codex_report(summary):
    """Per-session Codex surface with capability-aware, explicitly partial telemetry."""
    ident, life = summary.get("identity") or {}, summary.get("lifecycle") or {}
    obs, signals = summary.get("observations") or {}, summary.get("signals") or {}
    coverage = summary.get("coverage") or {}
    project = html.escape(str(ident.get("project", "unknown")))
    model = html.escape(str(friendly_model(ident.get("model"))))
    sid = html.escape(str(ident.get("session_id", "unknown"))[:8])
    phase = html.escape(str(life.get("phase", "unknown")).replace("_", " "))
    note = html.escape(str(coverage.get("note", "Codex health telemetry is unavailable.")))
    total = _positive_int(obs.get("context_tokens"))
    window = _positive_int(obs.get("context_window_tokens"))
    partial = bool(total and window and signals.get("experimental"))
    if partial:
        pct = min(100, round(total / window * 100))
        telemetry = f'''<div class="card"><div class="muted">EXPERIMENTAL CONTEXT LOAD</div>
<div class="phase">{pct}%</div><div class="gauge"><i style="width:{pct}%"></i></div>
<div>{total/1000:.1f}K / {window/1000:.1f}K tokens · experimental S1 {signals.get("s1_load", "—")}</div>
<p class="muted">{note}</p><p class="muted">S2–S4 and the combined rot score remain unavailable.</p></div>'''
    else:
        telemetry = f'''<div class="card"><b>Health score unavailable</b><p>{note}</p>
<p class="muted">Context tokens and S1–S4 require explicit experimental Codex rollout access until stable hook telemetry exists.</p></div>'''
    now = datetime.datetime.now().strftime("%H:%M:%S")
    return f'''<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="2"><title>Context Lens · Codex</title><style>
:root{{--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--muted:#706f6a;--grid:#e1e0d9;--accent:#2a78d6}}
@media(prefers-color-scheme:dark){{:root{{--surface:#1a1a19;--plane:#0d0d0d;--ink:#fff;--muted:#aaa99f;--grid:#2c2c2a;--accent:#3987e5}}}}
*{{box-sizing:border-box}}body{{font:14px/1.5 system-ui,sans-serif;background:var(--plane);color:var(--ink);max-width:720px;margin:auto;padding:24px}}
.card{{background:var(--surface);border:1px solid var(--grid);border-radius:8px;padding:18px 20px;margin-bottom:12px}}h1{{font-size:17px;margin:0}}.muted{{color:var(--muted);font-size:12px}}.phase{{font-size:38px;font-weight:700;margin:8px 0}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}.metrics b{{display:block;font-size:22px}}.gauge{{height:12px;background:var(--grid);border-radius:6px;overflow:hidden;margin:8px 0}}.gauge i{{display:block;height:100%;background:var(--accent)}}a{{color:var(--accent)}}
</style></head><body><div class="card"><h1>Context Lens · Codex <span class="muted">⟳ live · {now}</span></h1>
<div>{project} · {model} · session {sid} · <a href="../all-sessions.html">all sessions</a></div></div>
<div class="card"><div class="muted">SESSION PHASE</div><div class="phase">{phase}</div>
<div class="muted">Lifecycle events are observed directly from Codex hooks.</div></div>
<div class="card metrics"><div><b>{obs.get("turns_completed", 0)}</b><span class="muted">turns completed</span></div>
<div><b>{obs.get("tool_events", 0)}</b><span class="muted">tool events</span></div>
<div><b>{obs.get("compactions_observed", 0)}</b><span class="muted">compactions</span></div></div>
{telemetry}
</body></html>'''


def parse_timestamp(value):
    try:
        parsed = datetime.datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)


def relative_age(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def read_summaries(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    active, ended = [], []
    roots = [CACHE_ROOT]
    if CACHE_ROOT == DEFAULT_CACHE_ROOT and LEGACY_CLAUDE_CACHE_ROOT != CACHE_ROOT:
        roots.append(LEGACY_CLAUDE_CACHE_ROOT)
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        for directory in root.iterdir():
            if not directory.is_dir():
                continue
            try:
                item = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
                if not valid_summary(item):
                    continue
                ident = item.get("identity") or {}
                key = (ident.get("host", "claude-code"), ident.get("session_id", directory.name))
                if key in seen:
                    continue
                seen.add(key)
                item["_directory"] = directory.name
                item["_report_path"] = str(directory / "report.html")
                life = item.get("lifecycle") or {}
                if life.get("status") == "ended":
                    ended_at = parse_timestamp(life.get("ended_at"))
                    if (now - ended_at).total_seconds() <= RECENT_ENDED_SECONDS:
                        ended.append(item)
                else:
                    active.append(item)
            except (OSError, json.JSONDecodeError, AttributeError):
                continue
    key = lambda x: parse_timestamp((x.get("lifecycle") or {}).get("last_event_at"))
    active.sort(key=key, reverse=True)
    ended.sort(key=key, reverse=True)
    return active, ended[:RECENT_ENDED_LIMIT]


def overview_card(item, now):
    ident, life = item.get("identity") or {}, item.get("lifecycle") or {}
    obs, sig, health = item.get("observations") or {}, item.get("signals") or {}, item.get("health") or {}
    coverage = item.get("coverage") or {}
    experimental = bool(sig.get("experimental") and
                        str(coverage.get("context_tokens", "")).startswith("experimental"))
    zone = health.get("zone") if health.get("zone") in ("GREEN", "AMBER", "RED") else \
        ("PARTIAL" if experimental else "UNAVAILABLE")
    score = html.escape(str(health.get("rot_score", "—")))
    color = {"GREEN": "var(--good)", "AMBER": "var(--warning)", "RED": "var(--critical)",
             "PARTIAL": "var(--link)"}.get(zone, "var(--muted)")
    phase = str(life.get("phase", "unknown")).replace("_", " ")
    age_seconds = (now - parse_timestamp(life.get("last_event_at"))).total_seconds()
    stale = life.get("phase") == "running" and age_seconds > STALE_RUNNING_SECONDS
    phase_label = phase + (" · update stale (estimate)" if stale else "")
    total = obs.get("context_tokens", 0)
    total = total if isinstance(total, (int, float)) and not isinstance(total, bool) else 0
    window = obs.get("context_window_tokens", WINDOW)
    window = window if isinstance(window, (int, float)) and not isinstance(window, bool) and window > 0 else WINDOW
    pct = min(100, round(total / window * 100)) if window else 0
    report_path = Path(item.get("_report_path") or (CACHE_ROOT / item.get("_directory", "") / "report.html"))
    report = html.escape(report_path.resolve().as_uri(), quote=True)
    link = f'<a href="{report}">session report →</a>' if report_path.exists() else ""
    project = html.escape(str(ident.get("project", "unknown")))
    model = html.escape(str(friendly_model(ident.get("model"))))
    host = html.escape(str(ident.get("host", "claude-code")))
    sid = html.escape(str(ident.get("session_id", "unknown"))[:8])
    reason = html.escape(str(life.get("end_reason") or ""))
    end_note = f" · ended: {reason}" if life.get("status") == "ended" else ""
    signal_values = "/".join(html.escape(str(sig.get(k, "—"))) for k in
                             ("s1_load", "s2_exploration", "s3_dead_weight", "s4_instruction_distance"))
    dead = obs.get("dead_weight_percent", 0)
    dead = dead if isinstance(dead, (int, float)) and not isinstance(dead, bool) else 0
    if experimental:
        metric_html = (f'<span>context <b>{total/1000:.1f}K / {window/1000:.1f}K experimental</b></span>'
                       f'<span>S1 <b>{sig.get("s1_load", "—")}</b></span>'
                       '<span>S2–S4 <b>unavailable</b></span>')
    elif coverage.get("context_tokens") in ("unavailable", "pending experimental token_count observation"):
        metric_html = (f'<span>events <b>{obs.get("tool_events", 0)} tools / '
                       f'{obs.get("turns_completed", 0)} turns</b></span>'
                       '<span>context and S1–S4 <b>unavailable</b></span>')
    else:
        metric_html = (f'<span>context <b>{total/1000:.1f}K / {window/1000:.0f}K</b></span>'
                       f'<span>dead <b>{dead}%</b></span>'
                       f'<span>S1/S2/S3/S4 <b>{signal_values}</b></span>')
    return f'''<article class="session" style="border-left-color:{color}">
<div class="session-head"><div><h3>{project}</h3><span class="muted">{host} · {model} · session {sid}</span></div>
<span class="zone" style="color:{color}">{zone} · R{score}</span></div>
<div class="phase">{html.escape(phase_label)}{end_note} · updated {relative_age(age_seconds)}</div>
<div class="gauge"><i style="width:{pct}%;background:{color}"></i></div>
<div class="metrics">{metric_html}</div>
<div class="link">{link}</div></article>'''


def render_overview(active, ended, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    inactive = [s for s in active if (s.get("identity") or {}).get("host") == "codex"
                and (now - parse_timestamp((s.get("lifecycle") or {}).get("last_event_at"))).total_seconds()
                > CODEX_INACTIVE_SECONDS]
    inactive_ids = {s.get("_directory") for s in inactive}
    current = [s for s in active if s.get("_directory") not in inactive_ids]
    attention = [s for s in current if (s.get("lifecycle") or {}).get("phase") == "needs_attention"
                 or (s.get("health") or {}).get("zone") == "RED"]
    attention_ids = {s.get("_directory") for s in attention}
    ordinary = [s for s in current if s.get("_directory") not in attention_ids]
    severity = {"RED": 0, "AMBER": 1, "GREEN": 2, "UNAVAILABLE": 3}
    skey = lambda s: (severity.get((s.get("health") or {}).get("zone", "UNAVAILABLE"), 3),
                      -parse_timestamp((s.get("lifecycle") or {}).get("last_event_at")).timestamp())
    attention.sort(key=skey)
    ordinary.sort(key=skey)
    inactive.sort(key=lambda s: parse_timestamp((s.get("lifecycle") or {}).get("last_event_at")), reverse=True)
    inactive = [s for s in inactive
                if (now - parse_timestamp((s.get("lifecycle") or {}).get("last_event_at"))).total_seconds()
                <= RECENT_ENDED_SECONDS][:RECENT_ENDED_LIMIT]
    red = sum((s.get("health") or {}).get("zone") == "RED" for s in current)

    def section(title, items, empty):
        cards = "".join(overview_card(s, now) for s in items) or f'<div class="empty">{empty}</div>'
        return f"<section><h2>{title} <span>{len(items)}</span></h2>{cards}</section>"

    stamp = now.astimezone().strftime("%H:%M:%S")
    body = (section("Needs attention", attention, "No sessions need attention.")
            + section("Active sessions", ordinary, "No other active sessions.")
            + section("Inactive (estimated)", inactive, "No inactive Codex sessions.")
            + section("Ended in the last 24 hours", ended, "No recently ended sessions."))
    return f'''<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="2"><title>Context Lens · all sessions</title><style>
:root{{--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--good:#0ca30c;--warning:#d88900;--critical:#d03b3b;--link:#2a78d6}}
@media(prefers-color-scheme:dark){{:root{{--surface:#1a1a19;--plane:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;--link:#3987e5}}}}
*{{box-sizing:border-box}}body{{font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--plane);color:var(--ink);max-width:1040px;margin:auto;padding:24px}}
h1{{font-size:20px;margin:0}}h2{{font-size:14px;text-transform:uppercase;letter-spacing:.06em;margin:24px 0 10px}}h2 span{{color:var(--muted)}}h3{{margin:0;font-size:16px}}
.header,.counts,.session,.empty{{background:var(--surface);border:1px solid var(--grid);border-radius:8px}}.header{{padding:18px 20px}}.muted,.phase{{color:var(--muted);font-size:12px}}
.counts{{display:grid;grid-template-columns:repeat(4,1fr);margin-top:12px}}.count{{padding:12px 16px;border-right:1px solid var(--grid)}}.count:last-child{{border:0}}.count b{{display:block;font-size:24px}}
.session{{padding:14px 16px;margin:8px 0;border-left:4px solid}}.session-head,.metrics{{display:flex;justify-content:space-between;gap:16px;align-items:center}}.zone{{font-weight:700}}.phase{{margin-top:6px}}
.gauge{{height:7px;background:var(--grid);border-radius:5px;overflow:hidden;margin:10px 0}}.gauge i{{display:block;height:100%}}.metrics{{justify-content:flex-start;flex-wrap:wrap;color:var(--ink2);font-size:12px}}.metrics span{{margin-right:18px}}.link{{text-align:right;margin-top:5px}}a{{color:var(--link)}}.empty{{padding:18px;color:var(--muted)}}
@media(max-width:620px){{.counts{{grid-template-columns:repeat(2,1fr)}}.count:nth-child(2){{border-right:0}}.session-head{{align-items:flex-start}}}}
</style></head><body><div class="header"><h1>Context Lens · all sessions</h1>
<div class="muted">Local, read-only health metadata · event-driven live view · refreshed {stamp}</div></div>
<div class="counts"><div class="count"><b>{len(current)}</b>active</div><div class="count"><b>{len(attention)}</b>need attention</div><div class="count"><b>{red}</b>RED</div><div class="count"><b>{len(ended)}</b>recently ended</div></div>{body}
<p class="muted">No prompts, source code, tool output, transcript paths, or full working-directory paths are displayed.</p></body></html>'''


def write_overview():
    """Serialize aggregate rendering across concurrent Claude sessions."""
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    lock = CACHE_ROOT / ".overview.lock"
    deadline = time.monotonic() + 0.15
    acquired = False
    while time.monotonic() < deadline:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 5:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            time.sleep(0.01)
    out = CACHE_ROOT / "all-sessions.html"
    if not acquired:
        return out
    try:
        active, ended = read_summaries()
        atomic_write(out, render_overview(active, ended))
        return out
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


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


def open_all():
    overview = write_overview()
    open_browser(overview)
    return overview


def open_current():
    sid = os.environ.get("CODEX_THREAD_ID")
    if not sid:
        sys.exit("context-lens: CODEX_THREAD_ID is unavailable; use --open-all")
    report = session_dir(sid) / "report.html"
    if not report.exists():
        summary = load_summary(sid)
        if not summary:
            sys.exit("context-lens: current Codex session has not emitted a Context Lens hook yet")
        atomic_write(report, render_codex_report(summary))
    open_browser(report)
    return report


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
    elif "--open-all" in argv:
        print(open_all().as_uri())
    elif "--open-current" in argv:
        print(open_current().as_uri())
    elif "--prompt-note" in argv:
        out = prompt_note(json.load(sys.stdin))
        if out:
            print(json.dumps(out))
    elif "--session-start" in argv:
        session_start(json.load(sys.stdin))
    elif "--session-end" in argv:
        session_end(json.load(sys.stdin))
    elif "--notification" in argv:
        notification(json.load(sys.stdin))
    elif "--permission-request" in argv:
        permission_request(json.load(sys.stdin))
    elif "--precompact" in argv:
        precompact(json.load(sys.stdin))
    elif "--postcompact" in argv:
        postcompact(json.load(sys.stdin))
    elif "--line" in argv:
        print(line(json.load(sys.stdin)))
    elif "--html" in argv:
        out = Path(argv[argv.index("--html") + 1])
        path = path or find_transcript()
        d = analyze(path)
        out.write_text(render_html(d, [d["r"]], path))
        print(out)
    else:
        sys.exit("usage: analyzer.py --report|--update|--refresh|--line|--open|--open-all|"
                 "--open-current|--session-start|--session-end|--notification|"
                 "--permission-request|--precompact|--postcompact|--html OUT [--transcript PATH]")


if __name__ == "__main__":
    main(sys.argv[1:])
