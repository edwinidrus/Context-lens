#!/usr/bin/env python3
"""One runnable check for analyzer.py — fixture transcript + boundary asserts."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
import analyzer


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


def main():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.jsonl"
        fixture(p)
        d = analyzer.analyze(p)

    # exact total from latest MAIN-chain assistant usage (sidechain 999999 excluded)
    assert d["total"] == 96_000, d["total"]
    # latest model wins, mapped to friendly name; unmapped falls back to raw id
    assert d["model"] == "claude-opus-4-8"
    assert analyzer.friendly_model("claude-opus-4-8") == "Opus 4.8"
    assert analyzer.friendly_model("claude-new-9") == "claude-new-9"
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
    assert "Rot score" in rep and d["zone"] in rep and "Opus 4.8" in rep

    # --- M2: dashboard + state + statusline ---
    html = analyzer.render_html(d, [10, 20, d["r"]], "t.jsonl")
    assert '<meta http-equiv="refresh" content="2">' in html
    assert "http://" not in html and "https://" not in html  # fully self-contained
    assert "Opus 4.8" in html and "claude-opus-4-8" in html  # friendly + raw id
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

    print("test_analyzer: ALL PASS")


if __name__ == "__main__":
    main()
