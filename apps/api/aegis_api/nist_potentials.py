"""NIST / external potential library helpers (no invented coefficients).

Downloads only from allowlisted hosts. Prefer published NIST IPR files;
OpenKIM / Colab entries are browse/link helpers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ALLOWED_DOWNLOAD_HOSTS = {
    "www.ctcms.nist.gov",
    "ctcms.nist.gov",
    "potentials.nist.gov",
}

USER_AGENT = "Aegis-PFM-Workbench/0.1 (+local; NIST IPR client)"


def load_library_index(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def filter_library(
    entries: list[dict[str, Any]],
    *,
    elements: list[str] | None = None,
    q: str = "",
    source: str | None = None,
) -> list[dict[str, Any]]:
    out = entries
    if source:
        out = [e for e in out if (e.get("source") or "").lower() == source.lower()]
    if elements:
        want = {e.strip() for e in elements if e.strip()}
        # Keep entries that cover all requested elements (superset OK) OR browse helpers
        out = [
            e
            for e in out
            if want <= set(e.get("elements") or [])
            or "browse" in (e.get("recommended_for") or [])
        ]
    if q:
        needle = q.lower()
        out = [
            e
            for e in out
            if needle in (e.get("name") or "").lower()
            or needle in (e.get("id") or "").lower()
            or needle in " ".join(e.get("elements") or []).lower()
            or needle in (e.get("pair_style") or "").lower()
            or needle in (e.get("citation") or "").lower()
        ]
    return out


def is_allowed_download_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_DOWNLOAD_HOSTS:
        return False
    path = parsed.path or ""
    # Prefer NIST Download paths; still allow other paths on allowlisted hosts
    if host.endswith("ctcms.nist.gov") and "/potentials/Download/" not in path:
        return False
    return True


def download_bytes(url: str, *, timeout_s: float = 60.0) -> tuple[bytes, str]:
    if not is_allowed_download_url(url):
        raise ValueError(
            "Download URL host/path not allowlisted. Use NIST IPR Download links "
            "(www.ctcms.nist.gov/potentials/Download/...) or upload a file manually."
        )
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 — allowlisted hosts only
            data = resp.read()
            name = Path(urlparse(url).path).name or "potential.dat"
            return data, name
    except HTTPError as exc:
        raise ValueError(f"download failed HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"download failed: {exc.reason}") from exc


def parse_nist_entry_downloads(entry_url: str, *, timeout_s: float = 45.0) -> list[dict[str, str]]:
    """Scrape a NIST entry HTML page for Download links to potential parameter files."""
    parsed = urlparse(entry_url)
    host = (parsed.hostname or "").lower()
    if host not in {"www.ctcms.nist.gov", "ctcms.nist.gov"}:
        raise ValueError("Only NIST IPR entry pages can be scraped")
    if "/potentials/entry/" not in (parsed.path or ""):
        raise ValueError("URL must be a NIST /potentials/entry/... page")
    req = Request(entry_url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
        html = resp.read().decode("utf-8", errors="replace")
    rels = sorted(
        set(
            re.findall(
                r"(?:\.\./)+Download/([^\"'\s<>]+)",
                html,
            )
        )
    )
    out: list[dict[str, str]] = []
    for rel in rels:
        name = Path(rel).name
        if not re.search(r"\.(eam(\.(alloy|fs))?|fs|meam|alloy|set|dat)$", name, re.I):
            continue
        url = f"https://www.ctcms.nist.gov/potentials/Download/{rel}"
        out.append({"filename": name, "download_url": url})
    return out


def guess_formalism(pair_style: str, filename: str) -> str:
    style = (pair_style or "").lower().strip()
    name = filename.lower()
    if style in {"eam", "eam/alloy", "eam/fs", "meam", "snap", "table"}:
        return style if style != "eam" else "eam"
    if ".eam.fs" in name or name.endswith(".fs"):
        return "eam/fs"
    if ".eam.alloy" in name or name.endswith(".alloy"):
        return "eam/alloy"
    if ".meam" in name:
        return "meam"
    if ".eam" in name:
        return "eam/alloy"
    return "other"
