"""Export the lock for pip consumers, including the CUDA wheel index."""

import subprocess
from pathlib import Path

if __name__ == "__main__":
    body = subprocess.check_output(
        [
            "uv",
            "export",
            "--frozen",
            "--extra",
            "models",
            "--no-hashes",
            "--format",
            "requirements-txt",
            "--quiet",
        ],
        text=True,
    )
    Path("requirements.txt").write_text(
        "--extra-index-url https://download.pytorch.org/whl/cu128\n" + body,
        encoding="utf8",
    )
