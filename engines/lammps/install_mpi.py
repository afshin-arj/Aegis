"""Download / install MPI-capable LAMMPS on Windows (official MS-MPI packages)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from .mpi import discover_mpi, probe_lammps_parallelism

# Official prebuilt Windows packages that link against MS-MPI.
# See https://packages.lammps.org/windows.html / https://rpm.lammps.org/windows/
DEFAULT_MSMPI_URLS = (
    "https://rpm.lammps.org/windows/LAMMPS-64bit-latest-MSMPI.exe",
    "https://rpm.lammps.org/windows/LAMMPS-64bit-stable-MSMPI.exe",
    "https://packages.lammps.org/windows/LAMMPS-64bit-latest-MSMPI.exe",
    "https://packages.lammps.org/windows/LAMMPS-64bit-stable-MSMPI.exe",
)


def install_hint() -> dict[str, Any]:
    """UI / Engines panel hints for obtaining a parallel LAMMPS binary."""
    if platform.system() == "Windows":
        return {
            "platform": "Windows",
            "needs_msmpi_runtime": True,
            "installer_urls": list(DEFAULT_MSMPI_URLS),
            "manual_page": "https://packages.lammps.org/windows.html",
            "message": (
                "Windows GUI LAMMPS is serial. Install the official *-MSMPI.exe package "
                "(and MS-MPI runtime), then set AEGIS_LAMMPS_BIN to that lmp.exe. "
                "Aegis can download/run the installer via POST /api/engines/lammps/install-mpi."
            ),
        }
    return {
        "platform": platform.system(),
        "needs_msmpi_runtime": False,
        "installer_urls": [],
        "manual_page": "https://docs.lammps.org/Install.html",
        "message": (
            "Install an MPI-enabled LAMMPS (conda-forge `lammps`, module load, or source build "
            "with OpenMPI/MPICH), ensure mpirun/mpiexec is on PATH, then set AEGIS_LAMMPS_BIN."
        ),
    }


def _which_lammps() -> str | None:
    env = os.environ.get("AEGIS_LAMMPS_BIN", "").strip()
    if env and Path(env).exists():
        return str(Path(env).resolve())
    return shutil.which("lmp") or shutil.which("lmp.exe")


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as resp, dest.open("wb") as out:
        shutil.copyfileobj(resp, out)


def install_mpi_lammps_windows(
    *,
    force: bool = False,
    url: str | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Download and run the official Windows MS-MPI LAMMPS installer.

    The official installer replaces any prior user-level LAMMPS install (GUI or MSMPI).
    Requires the MS-MPI *runtime* already present for parallel launches afterwards.
    """
    if platform.system() != "Windows":
        hint = install_hint()
        return {
            "ok": False,
            "skipped": True,
            "message": hint["message"],
            "install": hint,
            "lammps_path": _which_lammps(),
            "probe": probe_lammps_parallelism(_which_lammps()),
            "mpi": discover_mpi(),
        }

    existing = _which_lammps()
    probe = probe_lammps_parallelism(existing)
    if existing and probe.get("lammps_mpi_capable") is True and not force:
        return {
            "ok": True,
            "skipped": True,
            "message": f"LAMMPS already looks MPI-capable: {existing}",
            "lammps_path": existing,
            "probe": probe,
            "mpi": discover_mpi(),
            "install": install_hint(),
        }

    urls = [url] if url else []
    env_url = os.environ.get("AEGIS_LAMMPS_MPI_URL", "").strip()
    if env_url:
        urls.append(env_url)
    urls.extend(DEFAULT_MSMPI_URLS)

    cache = cache_dir or Path(tempfile.gettempdir()) / "aegis-lammps-cache"
    cache.mkdir(parents=True, exist_ok=True)
    installer: Path | None = None
    used_url = ""
    errors: list[str] = []
    for u in urls:
        if not u:
            continue
        name = u.rstrip("/").split("/")[-1] or "LAMMPS-MSMPI.exe"
        dest = cache / name
        try:
            if dest.exists() and dest.stat().st_size > 50_000_000:
                installer = dest
                used_url = u
                break
            _download(u, dest)
            if dest.exists() and dest.stat().st_size > 50_000_000:
                installer = dest
                used_url = u
                break
            errors.append(f"{u}: download too small")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{u}: {exc}")

    if not installer:
        return {
            "ok": False,
            "message": "Could not download MS-MPI LAMMPS installer. " + "; ".join(errors[:3]),
            "install": install_hint(),
            "lammps_path": existing,
            "probe": probe,
            "mpi": discover_mpi(),
        }

    # NSIS silent flag used by LAMMPS Windows packages
    try:
        proc = subprocess.run(
            [str(installer), "/S"],
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        exit_code = proc.returncode
        if exit_code != 0:
            # Fall back to interactive (may require a desktop session)
            proc2 = subprocess.run([str(installer)], timeout=900, check=False)
            exit_code = proc2.returncode
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "message": f"Installer launch failed: {exc}",
            "installer": str(installer),
            "url": used_url,
            "install": install_hint(),
            "lammps_path": existing,
            "probe": probe,
            "mpi": discover_mpi(),
        }

    # Refresh discovery after install
    path = _which_lammps()
    # Common user-level install roots if PATH not refreshed in this process
    if not path:
        for root in (
            Path(os.environ.get("LOCALAPPDATA", "")) / "LAMMPS",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "LAMMPS",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "LAMMPS",
            Path.home() / "LAMMPS",
        ):
            if not root.exists():
                continue
            hits = list(root.rglob("lmp.exe"))
            if hits:
                path = str(hits[0].resolve())
                os.environ["AEGIS_LAMMPS_BIN"] = path
                break

    probe2 = probe_lammps_parallelism(path)
    mpi = discover_mpi()
    ok = bool(path) and probe2.get("lammps_mpi_capable") is not False
    return {
        "ok": ok,
        "message": (
            f"Installed MPI LAMMPS from {used_url}; binary={path}. "
            + (
                "Engines should show lmp MPI=likely — set mpi_procs>1 and re-run."
                if ok
                else "Installer finished but MPI capability not confirmed; reboot shell / set AEGIS_LAMMPS_BIN."
            )
        ),
        "installer": str(installer),
        "url": used_url,
        "exit_code": exit_code,
        "lammps_path": path,
        "probe": probe2,
        "mpi": mpi,
        "install": install_hint(),
    }
