#!/usr/bin/env python
import os
import sys

from setuptools import setup, Extension

sys.path.insert(0, os.path.dirname(__file__))
from nzpy_extended._version import get_versions

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
