"""Source and PyInstaller entry point."""
import os
import runpy
import sys
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
runpy.run_module("src.app", run_name="__main__")
