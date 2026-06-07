"""Exercise every runnable bash snippet in README.md.

We concatenate every ```bash``` fenced block (excluding ones tagged `notest`)
into a single bash script, prepend `set -euo pipefail` and a fresh `$RIP_TMP`,
then run the whole thing in one shell. The snippets share state — `$RIP_TMP`
exported in the first block is visible to every block after it — which is the
point: if you can read the README top-to-bottom and follow along, the test
follows the same path.

A fence tag is anything after the language on the opening backticks, e.g.
```` ```bash notest ````. Currently the only tag we honor is `notest` (skip
this block). Non-`bash` fences (e.g. ```yaml```) are always ignored.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


README = Path(__file__).resolve().parents[1] / "README.md"

_FENCE = re.compile(
    r"^```bash(?P<attrs>[^\n]*)\n(?P<body>.*?)\n```",
    re.MULTILINE | re.DOTALL,
)


def _bash_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for match in _FENCE.finditer(text):
        attrs = match.group("attrs").split()
        if "notest" in attrs:
            continue
        blocks.append(match.group("body"))
    return blocks


def test_readme_bash_snippets(rip_bin: str, restic_bin: str, tmp_path: Path) -> None:
    blocks = _bash_blocks(README.read_text())

    # Each fenced block becomes its own section in the assembled script.
    # We don't add `set -euo pipefail` between blocks (the prologue's flags
    # propagate), but we DO put each block in its own `{ ... }` group so a
    # syntax error inside one block is reported with the right block index.
    sections = []
    for i, body in enumerate(blocks):
        sections.append(f"# --- README block {i + 1} ---\n{body}")
    script = "set -euo pipefail\n\n" + "\n\n".join(sections) + "\n"

    script_path = tmp_path / "readme.sh"
    script_path.write_text(script)

    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not on PATH")

    bin_dir = Path(rip_bin).parent
    # Prepend rip + restic to the existing PATH instead of replacing it.
    # In a nix shell the system's coreutils live in /nix/store, not /usr/bin,
    # so we can't reset PATH to a hard-coded set of directories.
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{Path(restic_bin).parent}:{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path / "home"),
    }
    (tmp_path / "home").mkdir()

    result = subprocess.run(
        [bash, str(script_path)],
        capture_output=True, text=True, env=env,
    )

    if result.returncode != 0:
        pytest.fail(
            "README doctest failed (exit "
            f"{result.returncode}).\n"
            f"--- script ---\n{script}\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
