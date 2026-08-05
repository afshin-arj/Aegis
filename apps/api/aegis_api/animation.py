from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

# Match StructureViewer TYPE_COLORS (RGB)
_TYPE_COLORS = [
    (212, 137, 74),
    (91, 158, 201),
    (61, 154, 106),
    (201, 162, 39),
    (155, 123, 184),
    (212, 101, 85),
]


def build_trajectory_gif(
    job_dir: Path,
    *,
    max_frames: int = 40,
    max_atoms: int = 3000,
    size: int = 480,
    proj: str = "xy",
    duration_ms: int = 120,
    include_before: bool = True,
) -> bytes:
    """Render a lightweight 2D projection GIF from job dump frames.

    Stage bookmark dumps are excluded so the animation follows the cascade/
    implant/surface time series. Atom counts are stride-downsampled.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required for GIF export (pip install pillow)") from exc

    from aegis_api.trajectory import get_trajectory_frame, list_trajectory_frames

    frames_meta = list_trajectory_frames(job_dir, include_stages=False)
    if not frames_meta:
        raise FileNotFoundError("no dump frames found")

    selected = _select_frame_indices(frames_meta, max_frames=max_frames, include_before=include_before)
    if not selected:
        raise FileNotFoundError("no animation frames after filtering")

    proj_key = (proj or "xy").lower().strip()
    if proj_key not in {"xy", "xz", "yz"}:
        proj_key = "xy"

    size = max(160, min(int(size), 1024))
    max_atoms = max(100, min(int(max_atoms), 20000))
    duration_ms = max(40, min(int(duration_ms), 2000))

    images: list[Any] = []
    for fi in selected:
        payload = get_trajectory_frame(job_dir, fi, max_atoms=max_atoms, include_stages=False)
        images.append(
            _render_frame(
                payload,
                size=size,
                proj=proj_key,
                Image=Image,
                ImageDraw=ImageDraw,
            )
        )

    buf = BytesIO()
    images[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )
    return buf.getvalue()


def cache_trajectory_gif(job_dir: Path, gif_bytes: bytes, name: str = "animation.gif") -> Path:
    out = job_dir / name
    out.write_bytes(gif_bytes)
    return out


def _select_frame_indices(
    frames: list[dict[str, Any]],
    *,
    max_frames: int,
    include_before: bool,
) -> list[int]:
    before = [f for f in frames if f.get("role") == "before"]
    traj = [f for f in frames if f.get("role") != "before"]
    if not traj and before:
        traj = before
        before = []

    # Uniform stride so growth→peak→quench→residual all appear when many dumps exist
    cap = max(2, int(max_frames))
    if include_before and before and traj:
        # Reserve one slot for the pre-damage reference
        rest_cap = max(1, cap - 1)
        picked = [before[0]["index"], *_stride_pick(traj, rest_cap)]
    else:
        pool = traj or before
        picked = _stride_pick(pool, cap)
    # Deduplicate while preserving order
    seen: set[int] = set()
    out: list[int] = []
    for i in picked:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _stride_pick(frames: list[dict[str, Any]], cap: int) -> list[int]:
    if not frames:
        return []
    if len(frames) <= cap:
        return [f["index"] for f in frames]
    # Always include first and last
    if cap == 1:
        return [frames[-1]["index"]]
    idxs = [0]
    for k in range(1, cap - 1):
        idxs.append(round(k * (len(frames) - 1) / (cap - 1)))
    idxs.append(len(frames) - 1)
    # Unique while preserving order
    seen: set[int] = set()
    result: list[int] = []
    for i in idxs:
        if i not in seen:
            seen.add(i)
            result.append(frames[i]["index"])
    return result


def _render_frame(
    payload: dict[str, Any],
    *,
    size: int,
    proj: str,
    Image: Any,
    ImageDraw: Any,
) -> Any:
    bg = (18, 22, 30)
    box_color = (58, 69, 88)
    label_color = (180, 190, 205)
    img = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(img)

    box = payload.get("box") or {}
    lx = float(box.get("lx") or 1.0)
    ly = float(box.get("ly") or 1.0)
    lz = float(box.get("lz") or 1.0)
    if proj == "xz":
        ax_u, ax_v, dim_u, dim_v = "x", "z", lx, lz
    elif proj == "yz":
        ax_u, ax_v, dim_u, dim_v = "y", "z", ly, lz
    else:
        ax_u, ax_v, dim_u, dim_v = "x", "y", lx, ly

    margin = 28
    plot = size - 2 * margin
    scale = plot / max(dim_u, dim_v, 1e-6)
    # Center the projection
    ox = margin + (plot - dim_u * scale) * 0.5
    oy = margin + (plot - dim_v * scale) * 0.5

    # Box outline
    x0, y0 = ox, oy
    x1, y1 = ox + dim_u * scale, oy + dim_v * scale
    draw.rectangle([x0, y0, x1, y1], outline=box_color, width=1)

    atoms = payload.get("atoms") or []
    # Draw smaller atoms when dense
    r = 2 if len(atoms) > 1500 else 3 if len(atoms) > 600 else 4
    for a in atoms:
        u = float(a.get(ax_u, 0.0))
        v = float(a.get(ax_v, 0.0))
        # Flip v so +axis points up (image y grows downward)
        px = ox + u * scale
        py = oy + (dim_v - v) * scale
        t = int(a.get("type") or 1)
        color = _TYPE_COLORS[((t - 1) % len(_TYPE_COLORS) + len(_TYPE_COLORS)) % len(_TYPE_COLORS)]
        draw.ellipse([px - r, py - r, px + r, py + r], fill=color)

    ts = payload.get("timestep", "?")
    role = payload.get("role", "")
    n_full = payload.get("n_atoms_full", payload.get("n_atoms", 0))
    trunc = " · downsampled" if payload.get("truncated") else ""
    label = f"t={ts}  {proj}  n={n_full}{trunc}"
    if role == "before":
        label = "before  " + label
    draw.text((8, 6), label, fill=label_color)
    return img
