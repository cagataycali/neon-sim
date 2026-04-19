"""CLI entry points for neon-sim."""
import sys
import subprocess
from pathlib import Path


def convert_cmd():
    """Run the USDZ → textured MJCF converter (usd2mjcf_with_textures)."""
    here = Path(__file__).parent.parent / "scripts" / "usd2mjcf_with_textures.py"
    sys.exit(subprocess.call([sys.executable, str(here)] + sys.argv[1:]))
