"""Literature potential packager — provenance-only packaging of published content.

Never invents coefficients. Users must paste/upload published potential file text
and attest a DOI (or explicit unpublished-research attestation).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_STYLES = {
    "eam",
    "eam/alloy",
    "eam/fs",
    "meam",
    "snap",
    "table",
    "hybrid",
    "hybrid/overlay",
    "zbl",
    "tersoff",
}

SUITABILITY_DEFAULT = "unvalidated"


def _norm_doi(doi: str) -> str:
    d = (doi or "").strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    return d.strip()


def validate_literature_request(
    *,
    elements: list[str],
    lammps_pair_style: str,
    doi: str,
    citation: str,
    attestation: bool,
    unpublished_research: bool,
    content: bytes | str,
) -> list[str]:
    """Return list of blocking errors (empty = ok)."""
    errs: list[str] = []
    els = [e.strip() for e in elements if e and str(e).strip()]
    if not els:
        errs.append("Declare at least one element.")
    style = (lammps_pair_style or "").strip().lower()
    if style not in ALLOWED_STYLES:
        errs.append(f"pair_style '{lammps_pair_style}' not allowed.")
    if not attestation:
        errs.append("You must attest that the content comes from the cited published source (or marked unpublished research).")
    doi_n = _norm_doi(doi)
    if not doi_n and not unpublished_research:
        errs.append("DOI is required unless unpublished_research is set (not for citation).")
    if unpublished_research and not (citation or "").strip():
        errs.append("Unpublished research packs still need a citation note (author/lab/date).")
    if not (citation or "").strip() and doi_n:
        errs.append("Provide a short citation string alongside the DOI.")
    raw = content if isinstance(content, (bytes, bytearray)) else str(content).encode("utf-8")
    if not raw or not raw.strip():
        errs.append("Potential file content is empty — paste published tables/SI text or upload the published file.")
    if len(raw) < 40:
        errs.append("Content looks too short for a real potential file — paste the full published parameter file.")
    # Refuse obvious Aegis placeholders
    text = raw.decode("utf-8", errors="replace").lower()
    if "aegis placeholder" in text or "not valid coefficients" in text:
        errs.append("Refusing Aegis placeholder text — package only published potential content.")
    return errs


def write_literature_package(
    data_root: Path,
    *,
    name: str,
    elements: list[str],
    lammps_pair_style: str,
    formalism: str,
    doi: str,
    citation: str,
    source_url: str,
    content: bytes,
    filename: str,
    attestation: bool,
    unpublished_research: bool,
    notes: str = "",
    attach_to_id: str | None = None,
    pot_id: str | None = None,
) -> dict[str, Any]:
    """Write potential file + provenance JSON under data/potentials/user/<id>/."""
    els = [e.strip() for e in elements if e and str(e).strip()]
    style = lammps_pair_style.strip().lower()
    doi_n = _norm_doi(doi)
    pid = pot_id or attach_to_id or f"lit-{uuid.uuid4().hex[:10]}"
    dest_dir = data_root / "potentials" / "user" / pid
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename or "literature.potential").name
    if not safe_name or safe_name in {".", ".."}:
        safe_name = "literature.potential"
    dest = dest_dir / safe_name
    dest.write_bytes(content)
    rel = str(dest.relative_to(data_root)).replace("\\", "/")

    provenance = {
        "kind": "literature_package",
        "packaged_at": datetime.now(timezone.utc).isoformat(),
        "doi": doi_n,
        "citation": (citation or "").strip(),
        "source_url": (source_url or "").strip(),
        "attestation": bool(attestation),
        "unpublished_research": bool(unpublished_research),
        "notes": (notes or "").strip(),
        "original_filename": safe_name,
        "byte_length": len(content),
        "honesty": (
            "Aegis packaged user-supplied published content; coefficients were not invented or fitted by Aegis."
        ),
    }
    prov_path = dest_dir / "provenance.json"
    prov_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    prov_rel = str(prov_path.relative_to(data_root)).replace("\\", "/")

    warnings = [
        "Literature-packaged potential — unvalidated by Aegis until smoke tests / expert review.",
        provenance["honesty"],
    ]
    if unpublished_research:
        warnings.append("Marked unpublished research — not for citation as a peer-reviewed potential.")
    if style == "zbl":
        warnings.append("ZBL-only packs are ballistic/high-E stubs — not for residual damage physics.")

    suitability = "ballistic_only" if style == "zbl" else SUITABILITY_DEFAULT
    pair_coeff = f"pair_coeff * * {{file}} {' '.join(els)}"
    if style in {"zbl"}:
        pair_coeff = "pair_coeff * * {file}"  # user may edit; ZBL often uses type pairs

    return {
        "id": pid,
        "name": name.strip() or safe_name,
        "formalism": formalism,
        "elements": els,
        "recommended_for": ["cascade"] if suitability != "ballistic_only" else ["ballistic", "teaching"],
        "citation": (citation or "").strip(),
        "doi": doi_n,
        "source_url": (source_url or "").strip(),
        "warnings": warnings,
        "lammps_pair_style": style,
        "pair_coeff_template": pair_coeff,
        "file_path": rel,
        "source": "literature",
        "available": True,
        "is_placeholder": False,
        "suitability": suitability,
        "provenance": provenance,
        "provenance_path": prov_rel,
        "attach_to_id": attach_to_id,
    }
