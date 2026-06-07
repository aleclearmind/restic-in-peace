#!/usr/bin/env python3

import shutil
import subprocess
import sys
from pathlib import Path

from setuptools import setup, find_packages
from setuptools.command.build_py import build_py

from restic_in_peace import description, version

requirements = open("requirements.txt").readlines()


class build_py_with_restic_flags(build_py):
    """Regenerate restic_flags.json against the locally installed restic
    before staging Python files. Falls back to the shipped snapshot when
    restic is unavailable (e.g. CI that builds the wheel without restic on
    PATH)."""

    def run(self) -> None:
        restic = shutil.which("restic")
        target = Path(__file__).parent / "restic_in_peace" / "restic_flags.json"
        script = Path(__file__).parent / "scripts" / "generate_restic_flags.py"
        if restic and script.exists():
            try:
                subprocess.run(
                    [sys.executable, str(script), restic, str(target)],
                    check=True,
                )
                sys.stderr.write(f"regenerated {target} against {restic}\n")
            except subprocess.CalledProcessError as e:
                sys.stderr.write(
                    f"warning: failed to regenerate {target} ({e}); "
                    f"using shipped snapshot\n"
                )
        else:
            sys.stderr.write(
                f"warning: restic not on PATH or generator missing; "
                f"using shipped {target.name} snapshot\n"
            )
        super().run()


setup(
    name="restic-in-peace",
    version=version,
    description=description,
    url="https://rev.ng/gitlab/fcremo/restic-in-peace",
    author="fcremo",
    author_email="filippocremonese@gmail.com",
    license="TODO",
    packages=find_packages(),
    package_data={"restic_in_peace": ["restic_flags.json"]},
    include_package_data=True,
    zip_safe=False,
    install_requires=requirements,
    extras_require={"test": ["pytest"]},
    entry_points={"console_scripts": ["rip=restic_in_peace.main:entrypoint"]},
    cmdclass={"build_py": build_py_with_restic_flags},
)
