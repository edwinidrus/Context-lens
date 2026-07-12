#!/usr/bin/env python3
"""Render the README's LOCA-bench Table 1 chart as a dependency-free SVG."""

import csv
import math
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "benchmarks" / "loca-bench-table-1.csv"
OUTPUT = ROOT / "images" / "loca-bench-context-quality.svg"
LENGTHS = [8, 16, 32, 64, 96, 128, 256]
COLORS = ["#2563EB", "#D97706", "#059669", "#DC2626", "#7C3AED", "#0891B2", "#DB2777"]

WIDTH, HEIGHT = 1200, 850
LEFT, RIGHT, TOP, BOTTOM = 100, 44, 105, 270
PLOT_W = WIDTH - LEFT - RIGHT
PLOT_H = HEIGHT - TOP - BOTTOM


def x_pos(length):
    low, high = math.log2(LENGTHS[0]), math.log2(LENGTHS[-1])
    return LEFT + (math.log2(length) - low) / (high - low) * PLOT_W


def y_pos(score):
    return TOP + (100 - score) / 100 * PLOT_H


def text(x, y, value, css="label", anchor="start", extra=""):
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{css}" '
        f'text-anchor="{anchor}" {extra}>{escape(str(value))}</text>'
    )


def render():
    with DATA.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        'aria-labelledby="title description">',
        '<title id="title">LOCA-bench task accuracy falls as context workload grows</title>',
        '<desc id="description">Line chart of the seven models published in LOCA-bench Table 1, '
        'from 8K to 256K environment description tokens. Every model has lower task success '
        'accuracy at 256K than at 8K. A coverage note says that no author-published, like-for-like '
        'curves for newer model releases were verified as of 12 July 2026.</desc>',
        """<style>
        .title { font: 700 27px system-ui, -apple-system, sans-serif; fill: #111827; }
        .subtitle { font: 15px system-ui, -apple-system, sans-serif; fill: #4B5563; }
        .axis-title { font: 600 15px system-ui, -apple-system, sans-serif; fill: #374151; }
        .label { font: 13px system-ui, -apple-system, sans-serif; fill: #4B5563; }
        .legend { font: 13px system-ui, -apple-system, sans-serif; fill: #1F2937; }
        .source { font: 12px system-ui, -apple-system, sans-serif; fill: #6B7280; }
        .coverage { font: 600 13px system-ui, -apple-system, sans-serif; fill: #7C2D12; }
        .grid { stroke: #E5E7EB; stroke-width: 1; }
        .axis { stroke: #9CA3AF; stroke-width: 1.2; }
        .series { fill: none; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
        .point { stroke: #FFFFFF; stroke-width: 1.5; }
        </style>""",
        f'<rect width="{WIDTH}" height="{HEIGHT}" rx="18" fill="#FFFFFF"/>',
        text(LEFT, 42, "Agentic task success drops as context workload grows", "title"),
        text(
            LEFT,
            70,
            "Published model set (February 2026) · ReAct scaffold · execution-verified mean accuracy",
            "subtitle",
        ),
    ]

    for tick in range(0, 101, 20):
        y = y_pos(tick)
        svg.append(f'<line x1="{LEFT}" y1="{y:.1f}" x2="{WIDTH - RIGHT}" y2="{y:.1f}" class="grid"/>')
        svg.append(text(LEFT - 14, y + 5, tick, anchor="end"))

    svg.extend(
        [
            f'<line x1="{LEFT}" y1="{TOP}" x2="{LEFT}" y2="{TOP + PLOT_H}" class="axis"/>',
            f'<line x1="{LEFT}" y1="{TOP + PLOT_H}" x2="{WIDTH - RIGHT}" y2="{TOP + PLOT_H}" class="axis"/>',
        ]
    )

    for length in LENGTHS:
        x = x_pos(length)
        svg.append(f'<line x1="{x:.1f}" y1="{TOP + PLOT_H}" x2="{x:.1f}" y2="{TOP + PLOT_H + 7}" class="axis"/>')
        svg.append(text(x, TOP + PLOT_H + 27, f"{length}K", anchor="middle"))

    svg.append(
        text(
            25,
            TOP + PLOT_H / 2,
            "Task success accuracy (%)",
            "axis-title",
            "middle",
            f'transform="rotate(-90 25 {TOP + PLOT_H / 2:.1f})"',
        )
    )
    svg.append(
        text(
            LEFT + PLOT_W / 2,
            TOP + PLOT_H + 58,
            "Environment description length (tokens, log₂ scale)",
            "axis-title",
            "middle",
        )
    )

    for index, row in enumerate(rows):
        color = COLORS[index]
        scores = [float(row[f"{length}K"]) for length in LENGTHS]
        points = " ".join(f"{x_pos(length):.1f},{y_pos(score):.1f}" for length, score in zip(LENGTHS, scores))
        dash = ' stroke-dasharray="8 6"' if row["group"] == "Open source" else ""
        svg.append(f'<polyline points="{points}" class="series" stroke="{color}"{dash}/>')
        for length, score in zip(LENGTHS, scores):
            svg.append(
                f'<circle cx="{x_pos(length):.1f}" cy="{y_pos(score):.1f}" r="4.8" '
                f'class="point" fill="{color}"><title>{escape(row["model"])}: '
                f'{score:.1f}% at {length}K</title></circle>'
            )

    legend_y = 685
    svg.append(text(LEFT, legend_y - 20, "Proprietary", "axis-title"))
    svg.append(text(655, legend_y - 20, "Open source · dashed", "axis-title"))
    for index, row in enumerate(rows):
        if row["group"] == "Proprietary":
            group_index = index
            x, y = LEFT + (group_index % 3) * 178, legend_y
        else:
            group_index = index - 3
            x, y = 655 + (group_index % 2) * 250, legend_y + (group_index // 2) * 28
        dash = ' stroke-dasharray="8 6"' if row["group"] == "Open source" else ""
        svg.append(f'<line x1="{x}" y1="{y}" x2="{x + 30}" y2="{y}" stroke="{COLORS[index]}" stroke-width="3"{dash}/>')
        svg.append(text(x + 38, y + 5, row["model"], "legend"))

    svg.append('<rect x="100" y="755" width="1056" height="36" rx="7" fill="#FFF7ED" stroke="#FDBA74"/>')
    svg.append(text(
        LEFT + 14,
        778,
        "Coverage check · 12 Jul 2026: no author-published like-for-like curves for newer model releases were verified.",
        "coverage",
    ))
    svg.append(text(
        LEFT,
        825,
        "Source: Zeng, Huang & He (2026), LOCA-bench, Table 1 · Values unchanged; newer models are not estimated",
        "source",
    ))
    svg.append("</svg>")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(svg) + "\n", encoding="utf-8")
    print(OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    render()
