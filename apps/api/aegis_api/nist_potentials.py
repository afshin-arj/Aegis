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


def filter_library_for_acquire(
    entries: list[dict[str, Any]],
    *,
    elements: list[str],
) -> list[dict[str, Any]]:
    """Acquire filter: full cover, partial intersect, element-matched browse, or global search helpers."""
    want = {e.strip() for e in elements if e.strip()}
    if not want:
        return list(entries)
    global_helpers = {"nist-colab-search", "openkim-browse"}
    out: list[dict[str, Any]] = []
    for e in entries:
        el = set(e.get("elements") or [])
        browse = "browse" in (e.get("recommended_for") or [])
        eid = str(e.get("id") or "")
        if want <= el or (want & el) or eid in global_helpers or (browse and (want & el)):
            out.append(e)
    return out


def build_acquire_plan(
    *,
    material_id: str,
    elements: list[str],
    library_entries: list[dict[str, Any]],
    potentials: list[Any],
    installed_library_ids: set[str],
) -> dict[str, Any]:
    """Rank acquire actions for a material. Never invents coefficients."""
    want = [e for e in elements if e]
    want_set = set(want)
    pots = list(potentials)
    compatible = [p for p in pots if want_set <= set(getattr(p, "elements", None) or [])]
    ready = [p for p in compatible if bool(getattr(p, "available", False))]
    ready_ids = [p.id for p in ready]

    candidates = filter_library_for_acquire(library_entries, elements=want)
    suggestions: list[dict[str, Any]] = []

    for e in candidates:
        el = list(e.get("elements") or [])
        el_set = set(el)
        covers = want_set <= el_set if want_set else False
        browse = "browse" in (e.get("recommended_for") or [])
        downloadable = bool(e.get("download_url"))
        mapped = e.get("maps_to_catalog_id")
        mapped_pot = next((p for p in pots if p.id == mapped), None) if mapped else None
        installed = (
            e.get("id") in installed_library_ids
            or (mapped_pot is not None and bool(getattr(mapped_pot, "available", False)))
        )

        score = 0.0
        if covers and downloadable:
            score += 100.0
        elif covers:
            score += 35.0
        elif want_set & el_set:
            score += 12.0
        if want_set and want_set == el_set:
            score += 22.0
        if "cascade" in (e.get("recommended_for") or []) or "acquire" in (e.get("recommended_for") or []):
            score += 12.0
        if mapped:
            score += 8.0
        if installed:
            score += 40.0
        if browse and not downloadable:
            score += 6.0
        if len(el_set) >= 8:
            # Multi-element universal-mixing files: useful for alloys, deprioritized vs elemental
            score -= 8.0
        if not covers and not browse:
            score -= 15.0

        action = "download" if downloadable else "browse"
        if covers and downloadable:
            reason = "Published file covers all material elements — download and attach."
        elif covers and browse:
            reason = "Browse NIST/OpenKIM for a published file that covers this composition."
        elif want_set & el_set:
            reason = (
                f"Partial element overlap ({', '.join(sorted(want_set & el_set))}); "
                "may help locate a multi-component potential."
            )
        else:
            reason = "General search helper for this materials family."

        if installed:
            reason = "Already installed / attached — verify citation before production use."

        suggestions.append(
            {
                "rank": 0,
                "score": score,
                "action": action,
                "library_id": e.get("id"),
                "catalog_id": mapped,
                "title": e.get("name") or e.get("id"),
                "reason": reason,
                "elements": el,
                "downloadable": downloadable,
                "installed": bool(installed),
                "entry_url": e.get("entry_url") or "",
                "warnings": list(e.get("warnings") or []),
                "citation": e.get("citation") or "",
                "doi": e.get("doi") or "",
                "pair_style": e.get("pair_style") or "",
            }
        )

    suggestions.sort(key=lambda s: (-float(s["score"]), str(s.get("title") or "")))
    for i, s in enumerate(suggestions, start=1):
        s["rank"] = i

    # Cap UI list but keep enough browse options
    suggestions = suggestions[:16]

    next_steps: list[str] = []
    if ready_ids:
        next_steps.append(
            f"Ready potential(s) on disk: {', '.join(ready_ids)}. Cite the DOI before production science."
        )
    else:
        dl = next((s for s in suggestions if s["action"] == "download" and not s["installed"]), None)
        if dl:
            next_steps.append(
                f"Preferred: Download «{dl['title']}» (library id {dl['library_id']}) and attach to the matching catalog slot."
            )
        br = next((s for s in suggestions if s["action"] == "browse"), None)
        if br:
            next_steps.append(
                f"If no auto-download fits: Open «{br['title']}», pick a published file, then Import URL or Upload."
            )
        next_steps.append(
            "Aegis never invents pair coefficients. Placeholders remain dry-run only until a published file is attached."
        )
        if not any(want_set <= set(s.get("elements") or []) and s.get("downloadable") for s in suggestions):
            next_steps.append(
                "No downloadable library row fully covers this composition — use NIST browse, OpenKIM, or upload a cited file. "
                "Literature packager (Phase B) can package published parameters with a DOI."
            )
        if dl and (
            "16el" in str(dl.get("library_id") or "") or len(dl.get("elements") or []) >= 8
        ):
            next_steps.append(
                "Preferred download uses a multi-element universal-mixing potential — cross terms are not thoroughly "
                "validated; read the row warnings before production cascade work."
            )

    return {
        "material_id": material_id,
        "elements": want,
        "has_ready_potential": bool(ready_ids),
        "ready_potential_ids": ready_ids,
        "compatible_potential_ids": [p.id for p in compatible],
        "suggestions": suggestions,
        "next_steps": next_steps,
    }


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
