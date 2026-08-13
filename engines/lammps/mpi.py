"""MPI launcher helpers for local / HPC LAMMPS runs."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def discover_mpi() -> dict[str, Any]:
    """Locate ``mpiexec`` / ``mpirun`` (MS-MPI, OpenMPI, Intel MPI, etc.)."""
    env = os.environ.get("AEGIS_MPIEXEC", "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    for name in ("mpiexec", "mpiexec.exe", "mpirun", "mpirun.exe"):
        which = shutil.which(name)
        if which:
            candidates.append(Path(which))
    # Common Windows MS-MPI install locations
    for root in (
        Path(os.environ.get("MSMPI_BIN", "")),
        Path(r"C:\Program Files\Microsoft MPI\Bin"),
        Path(r"C:\Program Files (x86)\Microsoft MPI\Bin"),
    ):
        if root and str(root):
            candidates.extend([root / "mpiexec.exe", root / "mpiexec"])

    binary = next((str(c.resolve()) for c in candidates if c and c.exists() and c.is_file()), None)
    if binary:
        msg = f"MPI launcher found at {binary}."
    else:
        msg = (
            "MPI launcher not found. Install MS-MPI / OpenMPI and set AEGIS_MPIEXEC, "
            "or keep mpi_procs=1 for serial LAMMPS."
        )
    return {
        "mpi_found": binary is not None,
        "mpi_path": binary,
        "mpi_message": msg,
    }


def probe_lammps_parallelism(lammps_bin: str | None) -> dict[str, Any]:
    """Best-effort parse of ``lmp -h`` for MPI vs serial build."""
    if not lammps_bin:
        return {
            "lammps_mpi_capable": None,
            "lammps_parallel_hint": "LAMMPS binary not configured.",
        }
    text = ""
    try:
        proc = subprocess.run(
            [lammps_bin, "-h"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower()
    except Exception as exc:  # noqa: BLE001
        return {
            "lammps_mpi_capable": None,
            "lammps_parallel_hint": f"Could not probe LAMMPS (-h): {exc}",
        }

    serial = bool(re.search(r"\bserial\b", text)) and "mpi" not in text[:800]
    # Typical MPI builds mention MPI in the version banner
    mpi_banner = bool(re.search(r"\bmpi\b", text[:1200]))
    if mpi_banner and not serial:
        return {
            "lammps_mpi_capable": True,
            "lammps_parallel_hint": "LAMMPS help text mentions MPI — parallel ranks should work.",
        }
    if serial or "gui" in (lammps_bin or "").lower():
        return {
            "lammps_mpi_capable": False,
            "lammps_parallel_hint": (
                "This LAMMPS binary looks serial (or GUI installer). "
                "mpi_procs>1 needs an MPI-enabled build (conda / source / cluster module)."
            ),
        }
    return {
        "lammps_mpi_capable": None,
        "lammps_parallel_hint": (
            "Could not confirm MPI from ``lmp -h``. "
            "If mpi_procs>1 fails, install an MPI-enabled LAMMPS."
        ),
    }


def resolve_mpi_procs(params: dict[str, Any] | None = None) -> int:
    """Job params override env default ``AEGIS_MPI_PROCS`` (default 1)."""
    n = 1
    env = os.environ.get("AEGIS_MPI_PROCS", "").strip()
    if env:
        try:
            n = int(env)
        except ValueError:
            n = 1
    if params is not None and params.get("mpi_procs") is not None:
        try:
            n = int(params.get("mpi_procs"))
        except (TypeError, ValueError):
            pass
    return max(1, min(n, 256))


def build_lammps_command(
    lammps_bin: str,
    *,
    input_name: str = "in.aegis",
    mpi_procs: int = 1,
    mpi_path: str | None = None,
) -> list[str]:
    """Return argv for serial or MPI LAMMPS.

    Raises ``RuntimeError`` when mpi_procs>1 but no launcher is available.
    """
    n = max(1, int(mpi_procs))
    if n <= 1:
        return [lammps_bin, "-in", input_name]
    info = discover_mpi() if not mpi_path else {"mpi_found": True, "mpi_path": mpi_path}
    launcher = info.get("mpi_path")
    if not launcher:
        raise RuntimeError(
            f"mpi_procs={n} requested but no mpiexec/mpirun found. "
            "Set AEGIS_MPIEXEC or install MS-MPI/OpenMPI, or set mpi_procs=1."
        )
    # MS-MPI on Windows: prefer -localonly N (no SMPD password / network).
    # OpenMPI / Intel / Linux: mpiexec -n N …
    if os.name == "nt":
        return [str(launcher), "-localonly", str(n), lammps_bin, "-in", input_name]
    return [str(launcher), "-n", str(n), lammps_bin, "-in", input_name]
