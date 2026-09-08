"""Path & identifier safety guards.

The factory pushes untrusted inputs (task graph JSON, LLM output) onto the
filesystem. Every such input must pass these guards before it can influence
a path. Centralising them here keeps a single audited enforcement point
(blueprint §14 security-gate mindset), used by the orchestrator, the
reviewer and the LLM coder backend alike.

Rules enforced:
  * identifiers (project / task ids) may only contain [A-Za-z0-9_-] and
    must not start with '.' (blocks '..' and hidden-file tricks);
  * file paths must be *relative* and must resolve to a location strictly
    inside the granted base directory.
"""
from __future__ import annotations

import re
from pathlib import Path

# Identifiers used as directory / file names: letters, digits, '_' and '-'.
# Must start with an alphanumeric char so '.' and '..' can never slip in.
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")


def ensure_safe_id(value: str, *, field: str = "id") -> str:
    """Validate an identifier is safe to use as a single path segment.

    Raises ValueError on anything that could escape a directory.
    """
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise ValueError(
            f"unsafe {field} {value!r}: must match {SAFE_ID_RE.pattern!r}"
        )
    return value


def safe_join(base: Path, rel: str, *, field: str = "file") -> Path:
    """Join a *relative* path under *base* without allowing traversal.

    Rejects absolute paths, empty strings and any '..' traversal that would
    resolve outside *base*. Returns the resolved path located inside base.
    """
    if not isinstance(rel, str) or not rel:
        raise ValueError(f"unsafe {field} path {rel!r}: must be non-empty")
    if rel.startswith(("/", "\\")) or (len(rel) > 1 and rel[1] == ":"):
        # absolute posix path, absolute windows path, or drive-relative
        raise ValueError(f"unsafe {field} path {rel!r}: must be relative")
    base_resolved = base.resolve()
    joined = (base_resolved / rel).resolve()
    try:
        joined.relative_to(base_resolved)
    except ValueError:
        raise ValueError(
            f"unsafe {field} path {rel!r}: escapes base directory"
        ) from None
    return joined
