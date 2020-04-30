#!/usr/bin/env python3

from setuptools import setup, find_packages

from restic_in_peace import description, version

setup(name="restic-in-peace",
      version=version,
      description=description,
      url="https://rev.ng/gitlab/fcremo/restic-in-peace",
      author="fcremo",
      author_email="filippocremonese@gmail.com",
      license="TODO",
      packages=find_packages(),
      zip_safe=False,
      install_requires=["loguru", "requests"],
      entry_points={
            "console_scripts": ["restic-in-peace=restic_in_peace.main:entrypoint"]
      }
      )
