#!/usr/bin/env python3
"""Build a clean local Codex marketplace containing the Context Lens plugin."""
import argparse
import json
import shutil
import sys
from pathlib import Path


MARKETPLACE_NAME = "context-lens-local"
PLUGIN_NAME = "context-lens"
PACKAGE_FILES = (
    ".codex-plugin/plugin.json",
    "LICENSE",
    "scripts/analyzer.py",
    "skills/context-lens-monitor/SKILL.md",
    "skills/context-lens/SKILL.md",
)


def build(output):
    repo = Path(__file__).resolve().parent.parent
    output = Path(output).expanduser().resolve()
    try:
        output.relative_to(repo)
    except ValueError:
        pass
    else:
        raise ValueError("output must be outside the Context Lens repository")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output is not empty: {output}")

    plugin = output / "plugins" / PLUGIN_NAME
    plugin.mkdir(parents=True, exist_ok=False)

    # Package an explicit, reviewable allowlist instead of copying the working tree.
    # This prevents local transcripts, contracts, credentials, editor files, and other
    # untracked material from leaking into a marketplace artifact.
    for relative in PACKAGE_FILES:
        source = repo / relative
        destination = plugin / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    # Codex currently has no SessionEnd or Notification hook event. The source tree's
    # default hook file retains those events for Claude; the Codex artifact uses only
    # the event set documented and fixture-tested by this release.
    packaged_hooks = plugin / "hooks" / "hooks.json"
    packaged_hooks.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo / "hooks" / "codex-hooks.json", packaged_hooks)

    manifest = {
        "name": MARKETPLACE_NAME,
        "interface": {"displayName": "Context Lens Local"},
        "plugins": [{
            "name": PLUGIN_NAME,
            "source": {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Developer Tools",
        }],
    }
    market_file = output / ".agents" / "plugins" / "marketplace.json"
    market_file.parent.mkdir(parents=True, exist_ok=True)
    market_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return market_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", default="~/.codex/context-lens-marketplace")
    args = parser.parse_args(argv)
    try:
        market_file = build(args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"context-lens: {exc}\n")
    print(market_file.parent.parent.parent)


if __name__ == "__main__":
    main(sys.argv[1:])
