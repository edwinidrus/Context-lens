#!/usr/bin/env python3
"""Build a clean local Codex marketplace containing the Context Lens plugin."""
import argparse
import json
import shutil
import sys
from pathlib import Path


MARKETPLACE_NAME = "context-lens-local"
PLUGIN_NAME = "context-lens"


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
    ignore = shutil.ignore_patterns(
        ".git", ".agents", ".codex", "graphify-out", "__pycache__", "*.pyc", "*.pyo")
    shutil.copytree(repo, plugin, ignore=ignore, dirs_exist_ok=False)

    # Codex currently has no SessionEnd or Notification hook event. The source tree's
    # default hook file retains those events for Claude; the Codex artifact uses only
    # the event set documented and fixture-tested by this release.
    shutil.copyfile(plugin / "hooks" / "codex-hooks.json", plugin / "hooks" / "hooks.json")

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
