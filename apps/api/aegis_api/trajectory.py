from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator


def list_trajectory_frames(job_dir: Path) -> list[dict[str, Any]]:
    """Index dump frames for OVITO-like scrubbing.

    Prefers ``dump.initial.lammpstrj`` as the pre-damage reference, then
    chronological ``dump.cascade.*`` / ``dump.implant.*`` / ``dump.surface.*``.
    """
    frames: list[dict[str, Any]] = []
    index = 0

    initial = job_dir / "dump.initial.lammpstrj"
    if initial.exists():
        for local_i, meta in enumerate(_iter_frame_meta(initial)):
            frames.append(
                {
                    "index": index,
                    "timestep": meta["timestep"],
                    "n_atoms": meta["n_atoms"],
                    "file": initial.name,
                    "file_frame": local_i,
                    "role": "before" if local_i == 0 else "trajectory",
                }
            )
            index += 1

    dump_files = sorted(
        {
            *job_dir.glob("dump.cascade*.lammpstrj"),
            *job_dir.glob("dump.implant*.lammpstrj"),
            *job_dir.glob("dump.surface*.lammpstrj"),
            *job_dir.glob("dump.*.lammpstrj"),
        },
        key=_dump_sort_key,
    )
    for path in dump_files:
        if path.name == "dump.initial.lammpstrj":
            continue
        for local_i, meta in enumerate(_iter_frame_meta(path)):
            frames.append(
                {
                    "index": index,
                    "timestep": meta["timestep"],
                    "n_atoms": meta["n_atoms"],
                    "file": path.name,
                    "file_frame": local_i,
                    "role": "trajectory",
                }
            )
            index += 1

    if frames and not any(f["role"] == "before" for f in frames):
        frames[0]["role"] = "before"
    return frames


def get_trajectory_frame(
    job_dir: Path,
    frame_index: int,
    *,
    max_atoms: int = 12000,
) -> dict[str, Any]:
    frames = list_trajectory_frames(job_dir)
    if not frames:
        raise FileNotFoundError("no dump frames found")
    if frame_index < 0 or frame_index >= len(frames):
        raise IndexError(f"frame_index {frame_index} out of range 0..{len(frames)-1}")
    meta = frames[frame_index]
    path = job_dir / meta["file"]
    atoms, box, timestep = _read_frame_at(path, meta["file_frame"])
    truncated = False
    if len(atoms) > max_atoms:
        # Uniform stride downsample for interactive viz (not analysis)
        step = max(1, len(atoms) // max_atoms)
        atoms = atoms[::step][:max_atoms]
        truncated = True
    return {
        "index": frame_index,
        "timestep": timestep,
        "role": meta["role"],
        "file": meta["file"],
        "n_atoms_full": meta["n_atoms"],
        "n_atoms": len(atoms),
        "truncated": truncated,
        "box": {"lx": box[0], "ly": box[1], "lz": box[2]},
        "atoms": atoms,
    }


def _dump_sort_key(path: Path) -> tuple[int, str]:
    m = re.search(r"(\d+)\.lammpstrj$", path.name)
    if m:
        return (int(m.group(1)), path.name)
    return (10**12, path.name)


def _iter_frame_meta(path: Path) -> Iterator[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    starts = [i for i, line in enumerate(text) if line.startswith("ITEM: TIMESTEP")]
    for i in starts:
        try:
            ts = int(text[i + 1].strip().split()[0])
            j = i
            while j < len(text) and not text[j].startswith("ITEM: NUMBER OF ATOMS"):
                j += 1
            n = int(text[j + 1].strip())
            yield {"timestep": ts, "n_atoms": n, "line": i}
        except (ValueError, IndexError):
            continue


def _read_frame_at(path: Path, file_frame: int) -> tuple[list[dict[str, Any]], tuple[float, float, float], int]:
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    starts = [i for i, line in enumerate(text) if line.startswith("ITEM: TIMESTEP")]
    if file_frame < 0 or file_frame >= len(starts):
        raise IndexError("file_frame out of range")
    i = starts[file_frame]
    timestep = int(text[i + 1].strip().split()[0])
    while i < len(text) and not text[i].startswith("ITEM: NUMBER OF ATOMS"):
        i += 1
    n = int(text[i + 1].strip())
    while i < len(text) and not text[i].startswith("ITEM: BOX BOUNDS"):
        i += 1
    xlo, xhi = map(float, text[i + 1].split()[:2])
    ylo, yhi = map(float, text[i + 2].split()[:2])
    zlo, zhi = map(float, text[i + 3].split()[:2])
    while i < len(text) and not text[i].startswith("ITEM: ATOMS"):
        i += 1
    header = text[i].split()[2:]
    idx = {name: k for k, name in enumerate(header)}
    x_key = "x" if "x" in idx else "xu" if "xu" in idx else "xs" if "xs" in idx else None
    y_key = "y" if "y" in idx else "yu" if "yu" in idx else "ys" if "ys" in idx else None
    z_key = "z" if "z" in idx else "zu" if "zu" in idx else "zs" if "zs" in idx else None
    if x_key is None or y_key is None or z_key is None:
        raise KeyError("dump frame missing x/y/z columns")
    lx, ly, lz = xhi - xlo, yhi - ylo, zhi - zlo
    scaled = x_key == "xs"
    atoms: list[dict[str, Any]] = []
    for line in text[i + 1 : i + 1 + n]:
        parts = line.split()
        x = float(parts[idx[x_key]])
        y = float(parts[idx[y_key]])
        z = float(parts[idx[z_key]])
        if scaled:
            x = xlo + x * lx
            y = ylo + y * ly
            z = zlo + z * lz
        atoms.append(
            {
                "id": int(parts[idx.get("id", 0)]),
                "type": int(parts[idx.get("type", 1)]),
                "x": x,
                "y": y,
                "z": z,
            }
        )
    return atoms, (lx, ly, lz), timestep
