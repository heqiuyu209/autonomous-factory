"""Real data-source fetchers for Market Scout (blueprint V3).

Uses public JSON endpoints only (no API key required):
    reddit: https://www.reddit.com/search.json?q=...
    github: https://api.github.com/search/repositories?q=...

All fetchers are defensive: network errors / timeouts / bad payloads
return an empty list instead of raising, so the scout can degrade
gracefully to the deterministic recipe backend.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

TIMEOUT_SECONDS = 8.0
_USER_AGENT = "autonomous-factory-scout/0.3 (local CLI)"

# Overridable in tests via env vars.
REDDIT_API_BASE = os.environ.get("FACTORY_REDDIT_API_BASE", "https://www.reddit.com")
GITHUB_API_BASE = os.environ.get("FACTORY_GITHUB_API_BASE", "https://api.github.com")


@dataclass(frozen=True)
class Signal:
    """One piece of evidence fetched from a public source."""

    source: str
    title: str
    snippet: str
    url: str


Fetcher = Callable[[str, int], list[Signal]]


def _get_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def fetch_reddit(query: str, limit: int = 5, base_url: str | None = None) -> list[Signal]:
    """Fetch top Reddit post titles for a query."""
    base = (base_url or REDDIT_API_BASE).rstrip("/")
    url = f"{base}/search.json?q={urllib.parse.quote(query)}&limit={limit}&sort=relevance"
    data = _get_json(url)
    if not data or not isinstance(data.get("data"), dict):
        return []
    children = data["data"].get("children") or []
    signals: list[Signal] = []
    for child in children:
        post = (child or {}).get("data") or {}
        title = str(post.get("title") or "").strip()
        if not title:
            continue
        permalink = str(post.get("permalink") or "")
        signals.append(
            Signal(
                source="reddit",
                title=title[:200],
                snippet=str(post.get("selftext") or "")[:300].strip(),
                url=f"{base}{permalink}" if permalink else base,
            )
        )
    return signals


def fetch_github(query: str, limit: int = 5, base_url: str | None = None) -> list[Signal]:
    """Fetch top GitHub repositories for a query."""
    base = (base_url or GITHUB_API_BASE).rstrip("/")
    url = f"{base}/search/repositories?q={urllib.parse.quote(query)}&per_page={limit}"
    data = _get_json(url)
    if not data or not isinstance(data.get("items"), list):
        return []
    signals: list[Signal] = []
    for repo in data["items"]:
        full_name = str(repo.get("full_name") or "").strip()
        if not full_name:
            continue
        signals.append(
            Signal(
                source="github",
                title=full_name[:200],
                snippet=str(repo.get("description") or "")[:300].strip(),
                url=str(repo.get("html_url") or f"{base}/{full_name}"),
            )
        )
    return signals


SOURCE_FETCHERS: dict[str, Fetcher] = {
    "reddit": fetch_reddit,
    "github": fetch_github,
}
