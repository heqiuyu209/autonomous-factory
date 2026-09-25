"""Environment allow-list for running untrusted code.

Shared by the subprocess and docker sandboxes: whatever backend executes
LLM-generated code, the subprocess environment must NEVER inherit host
secrets. An injected payload could otherwise read OPENAI_API_KEY /
DATABASE_URL / any credential straight out of the environment.

Keep PATH / interpreter basics so toolchains resolve, drop everything
else, and re-check even allow-listed names against credential markers.
"""
from __future__ import annotations

import os

_VERIFIER_SAFE_ENV_KEYS = frozenset(
    {
        # OS / shell resolution (required for python/ruff to even start)
        "PATH",
        "SYSTEMROOT",
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "SYSTEMDRIVE",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "USERNAME",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "COMMONPROGRAMFILES",
        "APPDATA",
        "LOCALAPPDATA",
        # temp (pytest/ruff scratch space)
        "TEMP",
        "TMP",
        "TMPDIR",
        # interpreter behaviour (keep encoding deterministic)
        "PYTHONUTF8",
        "PYTHONIOENCODING",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONHASHSEED",
    }
)
# Anything that smells like a credential is dropped even if its name is
# not in the allow-list above. Conservative by construction: a name that
# merely contains a credential marker is safer to drop than to keep.
_SENSITIVE_ENV_MARKERS = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "AUTH",
)


def _verifier_env() -> dict[str, str]:
    """A minimal environment for running untrusted code.

    Allow-listed keys are kept; every remaining variable is dropped, and
    allow-listed names are re-checked against credential markers (e.g. a
    path variable that happens to embed a key name) so secrets never leak
    into the gate subprocess."""
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        name = k.upper()
        if k in _VERIFIER_SAFE_ENV_KEYS or name.startswith("PYTHON"):
            if not any(m in name for m in _SENSITIVE_ENV_MARKERS):
                env[k] = v
    return env
