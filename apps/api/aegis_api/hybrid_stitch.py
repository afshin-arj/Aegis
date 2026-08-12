"""Hybrid / ZBL stitch helper — assemble published many-body + ZBL overlays.

Never invents host coefficients. Requires an existing on-disk host potential and
user-supplied ZBL parameters with citation/attestation (published stitch recipe).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def validate_hybrid_stitch(
    *,
    host_pair_style: str,
    elements: list[str],
    zbl_pairs: list[dict[str, Any]],
    citation: str,
    doi: str,
    attestation: bool,
) -> list[str]:
    errs: list[str] = []
    if not attestation:
        errs.append("Attest that the ZBL stitch cutoffs/Z numbers come from a published recipe or validated lab note.")
    if not (citation or "").strip():
        errs.append("Citation required for the hybrid/ZBL stitch recipe.")
    host = (host_pair_style or "").strip().lower()
    if host in {"", "hybrid", "hybrid/overlay", "zbl"}:
        errs.append("Host pair_style must be a many-body style (e.g. eam/alloy, eam/fs, meam) — not hybrid/zbl alone.")
    els = [e.strip() for e in elements if e and str(e).strip()]
    if len(els) < 1:
        errs.append("Need at least one element.")
    if not zbl_pairs:
        errs.append("Provide at least one ZBL pair (type_i, type_j, z_i, z_j, cutoff_A).")
    for i, p in enumerate(zbl_pairs):
        try:
            zi = int(p.get("z_i"))
            zj = int(p.get("z_j"))
            cut = float(p.get("cutoff_A"))
            ti = int(p.get("type_i", 0))
            tj = int(p.get("type_j", 0))
        except (TypeError, ValueError):
            errs.append(f"ZBL pair #{i + 1}: z_i/z_j/cutoff_A/type_i/type_j must be numeric.")
            continue
        if zi <= 0 or zj <= 0:
            errs.append(f"ZBL pair #{i + 1}: atomic numbers must be positive.")
        if cut <= 0:
            errs.append(f"ZBL pair #{i + 1}: cutoff_A must be positive.")
        if ti < 1 or tj < 1:
            errs.append(f"ZBL pair #{i + 1}: type_i/type_j must be 1-based LAMMPS types.")
    if not (doi or "").strip():
        errs.append("DOI (or paper id) for the stitch recipe is required — do not invent cutoffs.")
    return errs


def build_hybrid_overlay_potential(
    *,
    data_root: Path,
    host_pot: dict[str, Any],
    host_file_rel: str,
    elements: list[str],
    zbl_pairs: list[dict[str, Any]],
    citation: str,
    doi: str,
    source_url: str = "",
    notes: str = "",
    name: str = "",
) -> dict[str, Any]:
    """Create a hybrid/overlay potential record pointing at the host file + ZBL lines."""
    host_style = str(host_pot.get("lammps_pair_style") or "eam/alloy").strip()
    els = [e.strip() for e in elements if e and str(e).strip()]
    host_line_tmpl = f"pair_coeff * * {host_style} {{file}} {{elements}}"

    zbl_lines = []
    for p in zbl_pairs:
        ti = int(p["type_i"])
        tj = int(p["type_j"])
        zi = int(p["z_i"])
        zj = int(p["z_j"])
        cut = float(p["cutoff_A"])
        zbl_lines.append(f"pair_coeff {ti} {tj} zbl {zi} {zj} {cut}")

    pair_style = f"hybrid/overlay {host_style} zbl"
    pid = f"hyb-{uuid.uuid4().hex[:10]}"
    provenance = {
        "kind": "hybrid_zbl_stitch",
        "packaged_at": datetime.now(timezone.utc).isoformat(),
        "host_potential_id": host_pot.get("id"),
        "host_file": host_file_rel,
        "host_pair_style": host_style,
        "zbl_pairs": zbl_pairs,
        "doi": (doi or "").strip(),
        "citation": (citation or "").strip(),
        "source_url": (source_url or "").strip(),
        "notes": (notes or "").strip(),
        "honesty": (
            "Aegis assembled hybrid/overlay lines from an existing host potential file and "
            "user-attested ZBL parameters — host coefficients were not invented."
        ),
    }
    dest_dir = data_root / "potentials" / "user" / pid
    dest_dir.mkdir(parents=True, exist_ok=True)
    prov_path = dest_dir / "provenance.json"
    prov_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    # Keep using the host file path (shared); do not copy binary to avoid license redistrib issues
    warnings = [
        "Hybrid/overlay ZBL stitch — verify inner cutoff vs PKA energy before cascade production.",
        provenance["honesty"],
        f"Host potential: {host_pot.get('id')} ({host_style}).",
        "Suitability starts unvalidated — expert-review the stitch before HPC / production cascades.",
    ]
    # Never inherit cascade_literature from the host — the overlay itself is unreviewed.
    host_suit = str(host_pot.get("suitability") or "")
    if host_suit:
        provenance["host_suitability"] = host_suit
    suitability = "unvalidated"

    return {
        "id": pid,
        "name": name.strip() or f"Hybrid ZBL overlay on {host_pot.get('id')}",
        "formalism": "other",
        "elements": els,
        "recommended_for": ["cascade", "high_e_pka"],
        "citation": (citation or "").strip(),
        "doi": (doi or "").strip(),
        "source_url": (source_url or "").strip(),
        "warnings": warnings,
        "lammps_pair_style": pair_style,
        "pair_coeff_template": host_line_tmpl,
        "pair_coeff_lines": [host_line_tmpl] + zbl_lines,
        "file_path": host_file_rel,
        "source": "hybrid_stitch",
        "available": True,
        "is_placeholder": False,
        "suitability": suitability,
        "provenance": provenance,
        "provenance_path": str(prov_path.relative_to(data_root)).replace("\\", "/"),
    }
