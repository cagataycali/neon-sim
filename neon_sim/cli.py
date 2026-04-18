"""CLI entry points for neon-sim."""
import sys
import subprocess
from pathlib import Path


def convert_cmd():
    """Run the Polycam → sim-ready USD converter."""
    here = Path(__file__).parent.parent / "scripts" / "convert_polycam.py"
    sys.exit(subprocess.call([sys.executable, str(here)] + sys.argv[1:]))
