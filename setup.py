#!/usr/bin/env python
import os
import sys

from setuptools import setup, Extension

sys.path.insert(0, os.path.dirname(__file__))
from nzpy_extended._version import get_versions

ext_modules = []
if not os.environ.get("NZPY_EXTENDED_NO_CEXT", "").lower() in ("1", "true", "yes"):
    ext_modules = [
        Extension(
            "nzpy_extended.c_ext",
            [os.path.join("nzpy_extended", "c_ext.c")],
        ),
    ]

setup(
    version=get_versions()["version"],
    ext_modules=ext_modules,
)
