#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$SCRIPT_DIR/.venv/bin/python"

if [ -x "$VENV_PY" ]; then
  "$VENV_PY" "$SCRIPT_DIR/run_roi_detector_gui.py"
else
  python3 "$SCRIPT_DIR/run_roi_detector_gui.py"
fi
