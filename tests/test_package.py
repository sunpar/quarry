import subprocess
import sys
from pathlib import Path

import quarry


def test_the_build_reads_the_package_version() -> None:
    built = subprocess.run(
        [sys.executable, "-m", "hatchling", "version"],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    assert built.stdout.strip() == quarry.__version__
