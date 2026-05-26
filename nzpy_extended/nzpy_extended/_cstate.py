"""Single source of truth for C extension availability.

Provides ``_HAVE_C_EXT`` and ``_c_ext``. All modules that need to
check or use the C extension import from here — never from each other.

Runtime monkeypatching ``_cstate._HAVE_C_EXT`` affects every consumer
because they read the attribute through the module reference (not a
cached local name).

For backward compatibility ``core._HAVE_C_EXT`` and ``core._c_ext`` are
also available via a module-level ``__getattr__`` that delegates to this
module dynamically, so monkeypatching is reflected there as well.
"""

from __future__ import annotations

import os
from typing import Any

_FORCE_PURE_PYTHON = (
    os.environ.get("NZPY_EXTENDED_NO_CEXT", "").lower() in ("1", "true", "yes")
)

if _FORCE_PURE_PYTHON:
    _HAVE_C_EXT: bool = False
    _c_ext: Any = None
else:
    try:
        from . import c_ext as _c_ext  # type: ignore[attr-defined,no-redef]

        _HAVE_C_EXT = True
    except ImportError:
        _HAVE_C_EXT = False
        _c_ext = None
