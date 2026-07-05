#!/usr/bin/env bash
# context-lens statusline: host JSON on stdin -> one gauge line (reads cached state, no reparse)
exec python3 "$(dirname "$0")/analyzer.py" --line
