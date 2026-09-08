"""Governance: capability policy per agent role (blueprint §13).

Every agent carries an explicit allow-list of what it may touch.
If a capability is not granted, it is DENIED by default.

Resource dimensions:
    internet    - which hosts/domains may be contacted
    filesystem  - which roots may be read/written
    secrets     - which secret stores are readable (max: NONE)
    cloud       - which cloud environments are reachable
    production  - production systems / billing access
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PolicyViolation(Exception):
    """Access outside the granted capability set."""


@dataclass(frozen=True)
class Capability:
    internet: tuple[str, ...] = ()  # "" = deny all; "*" = allowlist wildcard list
    filesystem: tuple[str, ...] = ("{worktree}",)  # roots allowed
    secrets: tuple[str, ...] = ()
    cloud: tuple[str, ...] = ()
    production: bool = False
    billing: bool = False


# Default policy per role - least privilege by construction.
DEFAULT_POLICIES: dict[str, Capability] = {
    "coder": Capability(
        internet=(),
        filesystem=("{worktree}",),
        secrets=(),
        cloud=(),
        production=False,
        billing=False,
    ),
    "reviewer": Capability(
        internet=(),
        filesystem=("{worktree}",),
        secrets=(),
        cloud=(),
        production=False,
        billing=False,
    ),
    "qa": Capability(
        internet=(),
        filesystem=("{worktree}",),
        secrets=(),
        cloud=(),
        production=False,
        billing=False,
    ),
    "devops": Capability(
        internet=("api.github.com",),
        filesystem=("{worktree}",),
        secrets=(),
        cloud=("staging",),
        production=False,
        billing=False,
    ),
    "market-scout": Capability(
        internet=(
            "www.reddit.com",
            "news.ycombinator.com",
            "api.github.com",
            "www.google.com",
        ),
        filesystem=(),
        secrets=(),
        cloud=(),
        production=False,
        billing=False,
    ),
    "ceo": Capability(  # governor: read-only foresight except budgets handled elsewhere
        internet=(),
        filesystem=("{worktree}",),
        secrets=(),
        cloud=(),
        production=False,
        billing=False,
    ),
}


def _matches(pattern: str, target: str) -> bool:
    if pattern == "*":
        return True
    if pattern == target:
        return True
    if pattern.endswith(".*") and target.startswith(pattern[:-1]):
        return True
    return False


class PolicyEngine:
    """Validates requested actions against a role's capability set."""

    def __init__(self, policies: dict[str, Capability] | None = None):
        self._policies = dict(DEFAULT_POLICIES)
        if policies:
            self._policies.update(policies)

    def capability_for(self, agent: str) -> Capability:
        return self._policies.get(agent, Capability())

    # -------- checks ----------------------------------------------------
    def check_internet(self, agent: str, host: str) -> None:
        cap = self.capability_for(agent)
        if not any(_matches(p, host) for p in cap.internet):
            raise PolicyViolation(
                f"agent '{agent}' is not allowed to contact '{host}'"
            )

    def check_filesystem(self, agent: str, path: str | Path, worktree: str) -> None:
        cap = self.capability_for(agent)
        resolved = str(Path(path).resolve())
        allowed = False
        for root in cap.filesystem:
            expanded = root.replace("{worktree}", str(Path(worktree).resolve()))
            if Path(resolved) == Path(expanded) or Path(resolved).is_relative_to(
                Path(expanded)
            ):
                allowed = True
                break
        if not allowed:
            raise PolicyViolation(
                f"agent '{agent}' cannot access '{resolved}' (outside granted roots)"
            )

    def check_secrets(self, agent: str, secret_id: str) -> None:
        cap = self.capability_for(agent)
        if not cap.secrets:
            raise PolicyViolation(
                f"agent '{agent}' has NO secrets access; asked for '{secret_id}'"
            )

    def assert_production(self, agent: str) -> None:
        cap = self.capability_for(agent)
        if not cap.production:
            raise PolicyViolation(
                f"agent '{agent}' is denied production access (granted: none)"
            )

    def assert_billing(self, agent: str) -> None:
        cap = self.capability_for(agent)
        if not cap.billing:
            raise PolicyViolation(f"agent '{agent}' is denied billing access")

    def summary(self, agent: str) -> dict:
        c = self.capability_for(agent)
        return {
            "agent": agent,
            "internet": list(c.internet) or ["DENY ALL"],
            "filesystem": [f.replace("{worktree}", "<worktree>") for f in c.filesystem],
            "secrets": list(c.secrets) or ["NONE"],
            "cloud": list(c.cloud) or ["NONE"],
            "production": c.production,
            "billing": c.billing,
        }
