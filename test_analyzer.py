#!/usr/bin/env python3
"""One runnable check for analyzer.py — fixture transcript + boundary asserts."""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
import analyzer
import build_codex_marketplace


def entry(etype, content, model=None, usage=None, sidechain=False):
    msg = {"content": content}
    if model:
        msg["model"] = model
    if usage:
        msg["usage"] = usage
    return {"type": etype, "isSidechain": sidechain, "message": msg}


def fixture(path):
    big = "x" * 4000  # ~1000 est tokens
    rows = [
        {"type": "mode"},  # noise, must be skipped
        entry("user", "please read the file"),
        entry("assistant",
              [{"type": "thinking", "thinking": big},
               {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a.py"}}],
              model="claude-fable-5",
              usage={"input_tokens": 10_000, "cache_creation_input_tokens": 5_000,
                     "cache_read_input_tokens": 5_000, "output_tokens": 10}),
        entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": big}]),
        entry("assistant",
              [{"type": "text", "text": big},
               {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/a.py"}}],
              model="claude-opus-4-8",
              usage={"input_tokens": 30_000, "cache_creation_input_tokens": 30_000,
                     "cache_read_input_tokens": 36_000, "output_tokens": 10}),
        entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": big}]),
        # sidechain entry: must be excluded entirely
        entry("assistant", [{"type": "text", "text": big}], model="claude-haiku-4-5-20251001",
              usage={"input_tokens": 999_999}, sidechain=True),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows))


def cool_fixture(path):
    rows = [
        entry("user", "hi"),
        entry("assistant", [{"type": "text", "text": "ok"}], model="claude-opus-4-8",
              usage={"input_tokens": 3_000}),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows))


def hot_fixture(path):
    big = "x" * 40_000  # ~10K est tokens per tool result
    rows = [
        entry("user", "do the thing"),
        entry("assistant", [{"type": "tool_use", "id": "h1", "name": "Read", "input": {"file_path": "/x"}}],
              model="claude-opus-4-8", usage={"input_tokens": 200_000}),
        entry("user", [{"type": "tool_result", "tool_use_id": "h1", "content": big}]),
        entry("assistant", [{"type": "tool_use", "id": "h2", "name": "Read", "input": {"file_path": "/x"}}],
              model="claude-opus-4-8", usage={"input_tokens": 200_000}),
        entry("user", [{"type": "tool_result", "tool_use_id": "h2", "content": big}]),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows))


def codex_fixture(path):
    rows = [
        {"type": "response_item", "payload": {"private_prompt": "do not persist me"}},
        {"timestamp": "2026-07-12T08:00:00+00:00", "type": "event_msg", "payload": {
            "type": "token_count", "info": {
                "last_token_usage": {"input_tokens": 80_000, "cached_input_tokens": 10_000,
                                     "output_tokens": 3_000, "reasoning_output_tokens": 2_000,
                                     "total_tokens": 95_000},
                "model_context_window": 200_000}}},
        {"type": "event_msg", "payload": {"type": "private_tool_output",
                                             "text": "secret source output"}},
        {"timestamp": "2026-07-12T08:01:00+00:00", "type": "event_msg", "payload": {
            "type": "token_count", "info": {
                "last_token_usage": {"input_tokens": 112_000, "cached_input_tokens": 12_000,
                                     "output_tokens": 4_000, "reasoning_output_tokens": 2_000,
                                     "total_tokens": 130_000},
                "model_context_window": 200_000}}},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows))


def main():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.jsonl"
        fixture(p)
        d = analyzer.analyze(p)

    # exact total from latest MAIN-chain assistant usage (sidechain 999999 excluded)
    assert d["total"] == 96_000, d["total"]
    # Latest model wins. Display labels are derived from arbitrary IDs, not a catalogue.
    assert d["model"] == "claude-opus-4-8"
    assert analyzer.friendly_model("claude-opus-4-8") == "Claude Opus 4.8"
    assert analyzer.friendly_model("gpt-5-2-codex") == "GPT 5.2 Codex"
    assert analyzer.friendly_model("google/gemini-2-5-pro") == "Google Gemini 2.5 Pro"
    assert analyzer.friendly_model("meta-llama/Llama-3-3-70b-instruct") == \
        "Meta Llama Llama 3.3 70B Instruct"
    assert analyzer.friendly_model(None) == "unknown"

    # Context capacity is metadata/config driven, so new proprietary and open-weight
    # model IDs work without adding entries to analyzer.py.
    assert analyzer.detect_context_window({"context_window_tokens": 1_000_000}) == \
        (1_000_000, "runtime metadata", True)
    assert analyzer.detect_context_window({"model": {"capabilities": {
        "contextWindow": {"maxTokens": 128_000}}}}) == (128_000, "runtime metadata", True)
    assert analyzer.detect_context_window({"config": {"n_ctx": 32_768}}) == \
        (32_768, "runtime metadata", True)
    assert analyzer.detect_context_window({}) == \
        (analyzer.DEFAULT_CONTEXT_WINDOW, "default estimate", False)

    with tempfile.TemporaryDirectory() as td:
        generic = Path(td) / "generic.jsonl"
        generic.write_text("\n".join(json.dumps(row) for row in [
            entry("user", "hello"),
            {"type": "assistant", "message": {
                "model": {"id": "acme/weights-72b-instruct"},
                "context_window_tokens": 131_072,
                "usage": {"input_tokens": 65_536},
                "content": [{"type": "text", "text": "ok"}]}}
        ]))
        generic_analysis = analyzer.analyze(generic)
        assert generic_analysis["model"] == "acme/weights-72b-instruct"
        assert generic_analysis["context_window"] == 131_072
        assert generic_analysis["context_window_exact"] is True
        generic_html = analyzer.render_html(generic_analysis, [0], generic)
        assert '<div class="hero">50%</div>' in generic_html
        assert "131.072K tokens" in generic_html and "capacity estimated" not in generic_html
    # composition: all four categories populated, fractions sum to 1
    comp = d["comp"]
    assert all(comp[k] > 0 for k in comp), comp
    fr = sum(v / sum(comp.values()) for v in comp.values())
    assert abs(fr - 1.0) < 1e-9
    # supersession: /a.py read twice -> first result (~1000 tok) dead
    assert d["dup_reads"] == 1
    assert 900 <= d["dead_tokens"] <= 1100, d["dead_tokens"]
    assert d["dead_items"] and "Read /a.py x2" in d["dead_items"][0][1]

    # S1 ramp boundaries (LOCA-bench anchors)
    for tok, want in [(31_000, 0), (32_000, 0), (96_000, 50), (128_000, 85), (200_000, 100)]:
        got = analyzer.s1_load(tok)
        assert got == want, (tok, got, want)
    # S3: 50% dead share -> 100 (paper: 50% tool-result clearing)
    assert analyzer.s3_dead_weight(50, 100) == 100
    assert analyzer.s3_dead_weight(0, 100) == 0
    # zone edges
    assert analyzer.zone(39) == "GREEN" and analyzer.zone(40) == "AMBER"
    assert analyzer.zone(69) == "AMBER" and analyzer.zone(70) == "RED"
    # report renders and mentions the zone
    rep = analyzer.render_report(d, "t.jsonl")
    assert "Rot score" in rep and d["zone"] in rep and "Claude Opus 4.8" in rep

    # --- M2: dashboard + state + statusline ---
    html = analyzer.render_html(d, [10, 20, d["r"]], "t.jsonl")
    assert '<meta http-equiv="refresh" content="2">' in html
    assert "http://" not in html and "https://" not in html  # fully self-contained
    assert "Claude Opus 4.8" in html and "claude-opus-4-8" in html  # friendly + raw id
    assert "capacity estimated" in html
    assert "prefers-color-scheme" in html and "polyline" in html
    segs = [float(m) for m in __import__("re").findall(r'stroke-dasharray="([\d.]+)', html)]
    assert abs(sum(segs) - (100 - 4)) < 1.0, segs  # 4 donut arcs, 1-unit gap each

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.jsonl"
        fixture(p)
        analyzer.CACHE_ROOT = Path(td) / "cache"  # keep test out of real ~/.claude
        analyzer.update({"transcript_path": str(p), "session_id": "s1"})
        sd = analyzer.session_dir("s1")
        assert (sd / "report.html").exists() and "refresh" in (sd / "report.html").read_text()
        st = analyzer.load_state("s1")
        assert st["r_history"] == [d["r"]] and st["zone"] == d["zone"]
        analyzer.update({"transcript_path": str(p), "session_id": "s1"})
        assert analyzer.load_state("s1")["r_history"] == [d["r"], d["r"]]  # appends

        # statusline: normal + null-safe early-session host JSON
        ln = analyzer.line({"context_window": {"used_percentage": 44},
                            "model": {"display_name": "Opus 4.8"}, "session_id": "s1"})
        assert "Opus 4.8" in ln and "44%" in ln and f"R{d['r']}" in ln
        analyzer.line({"context_window": {"used_percentage": 10, "context_window_size": 1_000_000},
                       "model": {"display_name": "Future model"}, "session_id": "s1"})
        assert analyzer.load_state("s1")["context_window"] == 1_000_000
        inherited = analyzer.analyze(p)
        analyzer.apply_session_window(inherited, analyzer.load_state("s1"))
        assert inherited["context_window"] == 1_000_000 and inherited["context_window_exact"]
        ln0 = analyzer.line({"context_window": {"used_percentage": None},
                             "model": {}, "session_id": "nope"})
        assert "0%" in ln0  # no crash on nulls / missing state

    # --- M3: S2 exploration, S4 instr distance, zone-crossing injection ---
    assert analyzer.s4_instr_distance(32_000, 100) == 100
    assert analyzer.s4_instr_distance(16_000, 100) == 50
    assert analyzer.s4_instr_distance(32_000, 0) == 0          # gated by s1
    assert analyzer.s2_exploration([4, 4, 1, 1], 100) == 75    # cadence halved+
    assert analyzer.s2_exploration([1, 1, 1], 100) == 0        # <4 turns -> no trend
    assert analyzer.s2_exploration([1, 1, 4, 4], 100) == 0     # rising, not a plateau
    assert analyzer.s2_exploration([4, 4, 2, 2], 0) == 0       # shallow context -> gated
    # analyze wires all four; full weights (no renorm) now that s2/s4 exist
    assert all(k in d for k in ("s1", "s2", "s3", "s4"))

    with tempfile.TemporaryDirectory() as td:
        analyzer.CACHE_ROOT = Path(td) / "cache"
        cool, hot = Path(td) / "cool.jsonl", Path(td) / "hot.jsonl"
        cool_fixture(cool); hot_fixture(hot)
        zc = analyzer.analyze(cool)["zone"]
        zh = analyzer.analyze(hot)["zone"]
        assert analyzer.ZONE_RANK[zh] > analyzer.ZONE_RANK[zc], (zc, zh)  # cool<hot

        h = {"session_id": "x"}
        assert analyzer.update({**h, "transcript_path": str(cool)}) is None  # first: no prior
        out = analyzer.update({**h, "transcript_path": str(hot)})            # crossing up
        assert out and "systemMessage" in out and zh in out["systemMessage"]
        # model-facing note queued, delivered once at next prompt, then gone
        note = analyzer.prompt_note(h)
        assert note and "context-lens" in note["hookSpecificOutput"]["additionalContext"]
        assert analyzer.prompt_note(h) is None                              # cleared
        # staying in the same zone emits nothing
        assert analyzer.update({**h, "transcript_path": str(hot)}) is None

    # --- M4: compaction before/after loop ---
    # unit: cleared totals + dead-weight-cleared proxy
    m, note = analyzer.compaction_diff({"total": 200_000, "dead": 27_000},
                                       {"total": 24_000, "dead_tokens": 0})
    assert "200K → 24K" in m and "−176K" in m and "27K" in m
    assert "FM4" in note

    with tempfile.TemporaryDirectory() as td:
        analyzer.CACHE_ROOT = Path(td) / "cache"
        cool, hot = Path(td) / "cool.jsonl", Path(td) / "hot.jsonl"
        cool_fixture(cool); hot_fixture(hot)
        h = {"session_id": "cmp"}
        # PreCompact snapshots the big pre-compaction context
        analyzer.precompact({**h, "transcript_path": str(hot)})
        st = analyzer.load_state("cmp")
        assert st["pre_compact"]["total"] == 200_000 and st["pre_compact"]["dead"] > 0
        # next Stop sees a shrunken transcript -> reports compaction, not a zone message
        out = analyzer.update({**h, "transcript_path": str(cool)})
        assert out and "compaction" in out["systemMessage"] and "200K" in out["systemMessage"]
        assert "pre_compact" not in analyzer.load_state("cmp")   # snapshot consumed
        note = analyzer.prompt_note(h)                            # model gets lossy caution
        assert note and "FM4" in note["hookSpecificOutput"]["additionalContext"]
        # no snapshot => ordinary turn, no compaction message
        assert analyzer.update({**h, "transcript_path": str(cool)}) is None

    # --- live-surfaces v2: PostToolUse refresh + --open resolution ---
    with tempfile.TemporaryDirectory() as td:
        analyzer.CACHE_ROOT = Path(td) / "cache"
        p = Path(td) / "t.jsonl"; fixture(p)
        h = {"transcript_path": str(p), "session_id": "rf"}
        analyzer.update(h)                                   # seed one completed turn
        before = list(analyzer.load_state("rf")["r_history"])
        assert analyzer.refresh(h) is None                   # refresh emits nothing
        st = analyzer.load_state("rf")
        assert st["r_history"] == before                     # mid-turn refresh must NOT append
        assert "r" in st and "zone" in st                    # but R/zone stay current
        assert (analyzer.session_dir("rf") / "report.html").exists()
        # refresh must not clobber a queued note / pre_compact snapshot
        st["pending_note"] = "keep"; st["pre_compact"] = {"total": 1, "dead": 0}
        (analyzer.session_dir("rf") / "state.json").write_text(json.dumps(st))
        analyzer.refresh(h)
        st2 = analyzer.load_state("rf")
        assert st2["pending_note"] == "keep" and st2["pre_compact"]["total"] == 1

        # --open resolution: renders the live report if the Stop hook never wrote one
        p2 = Path(td) / "fresh.jsonl"; fixture(p2)            # stem 'fresh' has no cache dir yet
        html = analyzer.find_report(str(p2))
        assert html.exists() and "refresh" in html.read_text()
        assert html.parent.name == "fresh"                   # keyed by session (transcript stem)

    # --- live multi-session command center ---
    with tempfile.TemporaryDirectory() as td:
        analyzer.CACHE_ROOT = Path(td) / "cache"
        p = Path(td) / "private-transcript.jsonl"; fixture(p)
        hook = {"transcript_path": str(p), "session_id": "monitor-one",
                "cwd": "/home/alice/secret/acme-app", "model": "claude-opus-4-8"}

        analyzer.session_start({**hook, "hook_event_name": "SessionStart"})
        sm = analyzer.load_summary("monitor-one")
        assert sm["schema"] == analyzer.SUMMARY_SCHEMA
        assert sm["identity"]["project"] == "acme-app"
        assert sm["lifecycle"]["status"] == "active" and sm["lifecycle"]["phase"] == "ready"

        analyzer.update({**hook, "hook_event_name": "Stop"})
        sm = analyzer.load_summary("monitor-one")
        assert sm["lifecycle"]["phase"] == "waiting"
        assert set(sm["observations"]) >= {"context_tokens", "dead_weight_percent"}
        assert set(sm["signals"]) >= {"s1_load", "s2_exploration", "s3_dead_weight",
                                       "s4_instruction_distance"}
        serialized = json.dumps(sm)
        assert "/home/alice/secret" not in serialized
        assert str(p) not in serialized and "please read the file" not in serialized

        analyzer.notification({**hook, "hook_event_name": "Notification",
                               "notification_type": "permission_prompt"})
        assert analyzer.load_summary("monitor-one")["lifecycle"]["phase"] == "needs_attention"
        analyzer.session_end({**hook, "hook_event_name": "SessionEnd", "reason": "prompt_input_exit"})
        ended = analyzer.load_summary("monitor-one")
        assert ended["lifecycle"]["status"] == "ended"
        assert ended["lifecycle"]["end_reason"] == "prompt_input_exit"
        analyzer.session_start({**hook, "hook_event_name": "SessionStart", "source": "resume"})
        resumed = analyzer.load_summary("monitor-one")
        assert resumed["lifecycle"]["status"] == "active"
        assert resumed["lifecycle"]["ended_at"] is None      # resume reactivates same id

        # Stale running is a display-only estimate, not an inferred SessionEnd.
        old = (analyzer.datetime.datetime.now(analyzer.datetime.timezone.utc)
               - analyzer.datetime.timedelta(minutes=10)).isoformat()
        resumed["lifecycle"].update({"phase": "running", "last_event_at": old})
        analyzer.atomic_write(analyzer.session_dir("monitor-one") / "summary.json",
                              json.dumps(resumed))

        # Retain only the newest 20 ended sessions from the last 24 hours; malformed and
        # older summaries are ignored without blocking the monitor.
        now = analyzer.datetime.datetime.now(analyzer.datetime.timezone.utc)
        for i in range(22):
            item = json.loads(json.dumps(ended))
            item["identity"]["session_id"] = f"ended-{i}"
            item["identity"]["project"] = f"project-{i}"
            item["lifecycle"]["last_event_at"] = (now - analyzer.datetime.timedelta(minutes=i)).isoformat()
            item["lifecycle"]["ended_at"] = item["lifecycle"]["last_event_at"]
            analyzer.atomic_write(analyzer.session_dir(f"ended-{i}") / "summary.json", json.dumps(item))
        too_old = json.loads(json.dumps(ended))
        too_old["identity"]["session_id"] = "ended-old"
        too_old["lifecycle"]["ended_at"] = (now - analyzer.datetime.timedelta(hours=25)).isoformat()
        too_old["lifecycle"]["last_event_at"] = too_old["lifecycle"]["ended_at"]
        analyzer.atomic_write(analyzer.session_dir("ended-old") / "summary.json", json.dumps(too_old))
        (analyzer.session_dir("broken") / "summary.json").write_text("{not json")
        analyzer.atomic_write(analyzer.session_dir("wrong-shape") / "summary.json",
                              json.dumps({"schema": analyzer.SUMMARY_SCHEMA, "lifecycle": []}))

        active, recent = analyzer.read_summaries(now)
        assert len(active) == 1 and len(recent) == analyzer.RECENT_ENDED_LIMIT
        overview = analyzer.render_overview(active, recent, now)
        assert "Context Lens · all sessions" in overview and "update stale (estimate)" in overview
        assert "acme-app" in overview and "ended-old" not in overview
        assert "/home/alice/secret" not in overview and str(p) not in overview
        out = analyzer.write_overview()
        assert out.exists() and '<meta http-equiv="refresh" content="2">' in out.read_text()

    # Concurrent hook writers leave complete summaries and one complete aggregate page.
    with tempfile.TemporaryDirectory() as td:
        analyzer.CACHE_ROOT = Path(td) / "cache"
        threads = []
        for i in range(6):
            h = {"session_id": f"parallel-{i}", "cwd": f"/workspace/project-{i}",
                 "model": "claude-opus-4-8", "hook_event_name": "SessionStart"}
            threads.append(threading.Thread(target=analyzer.session_start, args=(h,)))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        active, ended = analyzer.read_summaries()
        assert len(active) == 6 and not ended
        aggregate = analyzer.write_overview().read_text()
        assert all(f"project-{i}" in aggregate for i in range(6))
        assert aggregate.endswith("</html>")

    hooks = json.loads((Path(__file__).parent / "hooks" / "hooks.json").read_text())["hooks"]
    assert {"SessionStart", "SessionEnd", "Notification", "PermissionRequest", "PostCompact"} <= set(hooks)
    assert "--session-start" in hooks["SessionStart"][0]["hooks"][0]["command"]
    assert "--session-end" in hooks["SessionEnd"][0]["hooks"][0]["command"]
    assert "--notification" in hooks["Notification"][0]["hooks"][0]["command"]

    # --- Codex adapter: lifecycle-only by default ---
    saved_codex_experimental = os.environ.pop(analyzer.CODEX_EXPERIMENTAL_ENV, None)
    with tempfile.TemporaryDirectory() as td:
        analyzer.CACHE_ROOT = Path(td) / "cache"
        ch = {"_context_lens_host": "codex", "session_id": "codex-one",
              "transcript_path": "/home/alice/.codex/private-rollout.jsonl",
              "cwd": "/home/alice/secret/codex-project", "model": "gpt-5.4",
              "turn_id": "turn-1"}
        analyzer.session_start({**ch, "hook_event_name": "SessionStart", "source": "startup"})
        analyzer.prompt_note({**ch, "hook_event_name": "UserPromptSubmit",
                              "prompt": "private customer credential"})
        analyzer.refresh({**ch, "hook_event_name": "PostToolUse", "tool_name": "Bash",
                          "tool_input": {"command": "cat private.txt"},
                          "tool_response": "private source output"})
        analyzer.permission_request({**ch, "hook_event_name": "PermissionRequest"})
        assert analyzer.load_summary("codex-one")["lifecycle"]["phase"] == "needs_attention"
        analyzer.precompact({**ch, "hook_event_name": "PreCompact", "trigger": "auto"})
        analyzer.postcompact({**ch, "hook_event_name": "PostCompact", "trigger": "auto"})
        analyzer.update({**ch, "hook_event_name": "Stop", "last_assistant_message": "private"})

        codex = analyzer.load_summary("codex-one")
        assert codex["identity"]["host"] == "codex" and codex["identity"]["model"] == "gpt-5.4"
        assert codex["lifecycle"]["phase"] == "waiting"
        assert codex["observations"]["tool_events"] == 1
        assert codex["observations"]["turns_completed"] == 1
        assert codex["observations"]["compactions_observed"] == 1
        assert not codex["signals"] and not codex["health"]
        assert codex["coverage"]["context_tokens"] == "unavailable"
        serialized = json.dumps(codex)
        assert "private customer credential" not in serialized
        assert "private source output" not in serialized and "private-rollout" not in serialized
        report = (analyzer.session_dir("codex-one") / "report.html").read_text()
        assert "Health score unavailable" in report and "GPT 5.4" in report
        assert "private" not in report and "/home/alice/secret" not in report

        old = (analyzer.datetime.datetime.now(analyzer.datetime.timezone.utc)
               - analyzer.datetime.timedelta(minutes=31)).isoformat()
        codex["lifecycle"]["last_event_at"] = old
        analyzer.atomic_write(analyzer.session_dir("codex-one") / "summary.json", json.dumps(codex))
        active, ended = analyzer.read_summaries()
        overview = analyzer.render_overview(active, ended)
        assert "Inactive (estimated)" in overview and "codex · GPT 5.4" in overview
        assert "context and S1–S4 <b>unavailable" in overview

    # Explicit opt-in reads only numeric token_count metadata from the rollout tail.
    os.environ[analyzer.CODEX_EXPERIMENTAL_ENV] = "1"
    with tempfile.TemporaryDirectory() as td:
        analyzer.CACHE_ROOT = Path(td) / "cache"
        rollout = Path(td) / "rollout.jsonl"
        codex_fixture(rollout)
        ch = {"_context_lens_host": "codex", "session_id": "codex-experimental",
              "transcript_path": str(rollout), "cwd": "/workspace/codex-experimental",
              "model": "gpt-5.4"}
        observation = analyzer.codex_token_observation(ch)
        assert observation["context_tokens"] == 130_000
        assert observation["context_window_tokens"] == 200_000
        assert observation["input_tokens"] == 112_000
        assert "private" not in json.dumps(observation) and "secret" not in json.dumps(observation)

        analyzer.session_start({**ch, "hook_event_name": "SessionStart"})
        analyzer.update({**ch, "hook_event_name": "Stop"})
        codex = analyzer.load_summary("codex-experimental")
        assert codex["observations"]["context_tokens"] == 130_000
        assert codex["signals"]["s1_load"] == analyzer.s1_load(130_000)
        assert codex["signals"]["s2_exploration"] is None
        assert codex["signals"]["s3_dead_weight"] is None
        assert codex["signals"]["s4_instruction_distance"] is None
        assert not codex["health"]
        assert codex["coverage"]["context_tokens"].startswith("experimental")
        serialized = json.dumps(codex)
        assert "do not persist me" not in serialized and "secret source output" not in serialized

        report = (analyzer.session_dir("codex-experimental") / "report.html").read_text()
        assert "EXPERIMENTAL CONTEXT LOAD" in report and "130.0K / 200.0K tokens" in report
        assert "experimental S1" in report and "combined rot score remain unavailable" in report
        active, ended = analyzer.read_summaries()
        overview = analyzer.render_overview(active, ended)
        assert "PARTIAL · R—" in overview and "130.0K / 200.0K experimental" in overview
        assert "S2–S4 <b>unavailable" in overview

        incompatible = Path(td) / "incompatible.jsonl"
        incompatible.write_text(json.dumps({"type": "event_msg", "payload": {
            "type": "token_count", "info": {"new_schema": True}}}))
        bad = {**ch, "session_id": "codex-schema-drift", "transcript_path": str(incompatible)}
        analyzer.session_start({**bad, "hook_event_name": "SessionStart"})
        drift = analyzer.load_summary("codex-schema-drift")
        assert not drift["signals"] and not drift["health"]
        assert drift["coverage"]["context_tokens"].startswith("pending experimental")

    if saved_codex_experimental is None:
        os.environ.pop(analyzer.CODEX_EXPERIMENTAL_ENV, None)
    else:
        os.environ[analyzer.CODEX_EXPERIMENTAL_ENV] = saved_codex_experimental

    repo = Path(__file__).parent
    codex_manifest = json.loads((repo / ".codex-plugin" / "plugin.json").read_text())
    claude_manifest = json.loads((repo / ".claude-plugin" / "plugin.json").read_text())
    assert codex_manifest["name"] == "context-lens"
    assert codex_manifest["version"] == claude_manifest["version"] == "1.4.0"
    assert (repo / "images" / "dashboard.png").is_file()

    with tempfile.TemporaryDirectory() as td:
        market_file = build_codex_marketplace.build(Path(td) / "marketplace")
        market = json.loads(market_file.read_text())
        assert market["name"] == "context-lens-local"
        packaged = market_file.parents[2] / "plugins" / "context-lens"
        assert (packaged / ".codex-plugin" / "plugin.json").exists()
        packaged_files = {
            str(path.relative_to(packaged)) for path in packaged.rglob("*") if path.is_file()
        }
        expected_files = set(build_codex_marketplace.PACKAGE_FILES) | {"hooks/hooks.json"}
        assert packaged_files == expected_files, packaged_files ^ expected_files
        assert not any(path.suffix.lower() in {".pdf", ".env"} for path in packaged.rglob("*"))
        packaged_hooks = json.loads((packaged / "hooks" / "hooks.json").read_text())["hooks"]
        assert {"SessionStart", "UserPromptSubmit", "PermissionRequest", "PostToolUse",
                "PreCompact", "PostCompact", "Stop"} == set(packaged_hooks)
        assert "SessionEnd" not in packaged_hooks and "Notification" not in packaged_hooks

    print("test_analyzer: ALL PASS")


if __name__ == "__main__":
    main()
