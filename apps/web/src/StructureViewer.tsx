import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export type AtomXYZ = { id: number; type: number; x: number; y: number; z: number };
export type TrajFrameMeta = {
  index: number;
  timestep: number;
  n_atoms: number;
  file: string;
  role: string;
};
export type TrajIndex = {
  n_frames: number;
  frames: TrajFrameMeta[];
  before_index: number | null;
  after_indices: number[];
};
export type TrajFrame = {
  index: number;
  timestep: number;
  role: string;
  n_atoms: number;
  n_atoms_full: number;
  truncated: boolean;
  box: { lx: number; ly: number; lz: number; xlo?: number; ylo?: number; zlo?: number; triclinic?: boolean };
  type_symbols?: string[];
  structure_kind?: string;
  atoms: AtomXYZ[];
};

const TYPE_COLORS = [0xd4894a, 0x5b9ec9, 0x3d9a6a, 0xc9a227, 0x9b7bb8, 0xd46555];

export function StructureAtomCanvas({
  atoms,
  box,
  label,
}: {
  atoms: AtomXYZ[];
  box?: { lx: number; ly: number; lz: number };
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x07090d);
    const w = Math.max(el.clientWidth, 1);
    const h = Math.max(el.clientHeight, 1);
    const camera = new THREE.PerspectiveCamera(40, w / h, 0.1, 5000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(w, h);
    el.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0x8899aa, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 0.95);
    key.position.set(8, 14, 10);
    scene.add(key);

    const cx = (box?.lx ?? 0) / 2;
    const cy = (box?.ly ?? 0) / 2;
    const cz = (box?.lz ?? 0) / 2;
    const span = Math.max(box?.lx ?? 10, box?.ly ?? 10, box?.lz ?? 10, 4);

    if (box) {
      const edges = new THREE.EdgesGeometry(new THREE.BoxGeometry(box.lx, box.ly, box.lz));
      const line = new THREE.LineSegments(
        edges,
        new THREE.LineBasicMaterial({ color: 0x3a4558 })
      );
      line.position.set(cx, cy, cz);
      scene.add(line);
    }

    const group = new THREE.Group();
    const byType = new Map<number, AtomXYZ[]>();
    for (const a of atoms) {
      const list = byType.get(a.type) || [];
      list.push(a);
      byType.set(a.type, list);
    }
    const radius = Math.min(0.28, span * 0.035);
    for (const [type, list] of byType) {
      const geo = new THREE.SphereGeometry(radius, 8, 8);
      const mat = new THREE.MeshStandardMaterial({
        color: TYPE_COLORS[((Math.max(1, type) - 1) % TYPE_COLORS.length + TYPE_COLORS.length) % TYPE_COLORS.length],
        roughness: 0.42,
        metalness: 0.22,
      });
      const mesh = new THREE.InstancedMesh(geo, mat, list.length);
      const m = new THREE.Matrix4();
      list.forEach((a, i) => {
        m.setPosition(a.x, a.y, a.z);
        mesh.setMatrixAt(i, m);
      });
      mesh.instanceMatrix.needsUpdate = true;
      group.add(mesh);
    }
    scene.add(group);

    camera.position.set(cx + span * 1.15, cy + span * 0.85, cz + span * 1.35);
    camera.lookAt(cx, cy, cz);

    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let rotY = 0.35;
    let rotX = 0.25;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const onDown = (ev: PointerEvent) => {
      dragging = true;
      lastX = ev.clientX;
      lastY = ev.clientY;
      el.setPointerCapture(ev.pointerId);
    };
    const onUp = () => {
      dragging = false;
    };
    const onMove = (ev: PointerEvent) => {
      if (!dragging) return;
      rotY += (ev.clientX - lastX) * 0.008;
      rotX += (ev.clientY - lastY) * 0.008;
      rotX = Math.max(-1.2, Math.min(1.2, rotX));
      lastX = ev.clientX;
      lastY = ev.clientY;
    };
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    el.addEventListener("pointermove", onMove);

    let frame = 0;
    let alive = true;
    const animate = () => {
      if (!alive) return;
      frame = requestAnimationFrame(animate);
      if (!dragging && !reduce) rotY += 0.003;
      const dist = span * 1.85;
      camera.position.x = cx + dist * Math.sin(rotY) * Math.cos(rotX);
      camera.position.y = cy + dist * Math.sin(rotX) + span * 0.15;
      camera.position.z = cz + dist * Math.cos(rotY) * Math.cos(rotX);
      camera.lookAt(cx, cy, cz);
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      el.removeEventListener("pointermove", onMove);
      renderer.dispose();
      el.innerHTML = "";
    };
  }, [atoms, box?.lx, box?.ly, box?.lz]);

  return <div className="viz structure-viz" ref={ref} role="img" aria-label={label} />;
}

type Props = {
  jobId: string | null;
  refreshKey?: string;
};

export default function StructureViewer({ jobId, refreshKey }: Props) {
  const [index, setIndex] = useState<TrajIndex | null>(null);
  const [before, setBefore] = useState<TrajFrame | null>(null);
  const [after, setAfter] = useState<TrajFrame | null>(null);
  const [afterIdx, setAfterIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [scrubErr, setScrubErr] = useState("");
  const scrubReq = useRef(0);
  const pendingSeekTs = useRef<number | null>(null);

  const afterFrames = useMemo(() => index?.after_indices ?? [], [index]);

  useEffect(() => {
    // Invalidate any in-flight scrub from a previous job
    scrubReq.current += 1;
    pendingSeekTs.current = null;
    setAfter(null);
    setScrubErr("");

    if (!jobId) {
      setIndex(null);
      setBefore(null);
      setAfter(null);
      setErr("");
      setBusy(false);
      return;
    }
    let cancelled = false;
    setIndex(null);
    setBefore(null);
    setAfter(null);
    (async () => {
      setBusy(true);
      setErr("");
      try {
        const traj = await api<TrajIndex>(`/api/jobs/${jobId}/trajectory`);
        if (cancelled) return;
        setIndex(traj);
        if (traj.before_index != null) {
          const bf = await api<TrajFrame>(`/api/jobs/${jobId}/trajectory/${traj.before_index}`);
          if (cancelled) return;
          setBefore(bf);
        } else {
          setBefore(null);
        }
        const firstAfter = traj.after_indices[0];
        setAfterIdx(0);
        if (firstAfter != null) {
          const af = await api<TrajFrame>(`/api/jobs/${jobId}/trajectory/${firstAfter}`);
          if (cancelled) return;
          setAfter(af);
        } else {
          setAfter(null);
        }
      } catch (e) {
        if (!cancelled) setErr(String(e));
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
      scrubReq.current += 1;
    };
  }, [jobId, refreshKey]);

  useEffect(() => {
    const seekTo = (target: number) => {
      if (!index?.frames?.length || !afterFrames.length) {
        pendingSeekTs.current = target;
        return;
      }
      pendingSeekTs.current = null;
      let bestLocal = 0;
      let bestDist = Infinity;
      afterFrames.forEach((fi, local) => {
        const fr = index.frames.find((f) => f.index === fi);
        if (!fr) return;
        const d = Math.abs(Number(fr.timestep) - target);
        if (d < bestDist) {
          bestDist = d;
          bestLocal = local;
        }
      });
      void scrub(bestLocal);
    };
    const onSeek = (ev: Event) => {
      const detail = (ev as CustomEvent<{ timestep?: number }>).detail;
      seekTo(Number(detail?.timestep ?? 0));
    };
    window.addEventListener("aegis-seek-timestep", onSeek);
    if (pendingSeekTs.current != null && index?.frames?.length && afterFrames.length) {
      seekTo(pendingSeekTs.current);
    }
    return () => window.removeEventListener("aegis-seek-timestep", onSeek);
  }, [index, afterFrames, jobId]);

  async function scrub(i: number) {
    if (!jobId || !afterFrames.length) return;
    const clamped = Math.max(0, Math.min(i, afterFrames.length - 1));
    const reqId = ++scrubReq.current;
    setAfterIdx(clamped);
    setBusy(true);
    setScrubErr("");
    try {
      const frame = await api<TrajFrame>(`/api/jobs/${jobId}/trajectory/${afterFrames[clamped]}`);
      if (reqId !== scrubReq.current) return;
      setAfter(frame);
    } catch (e) {
      if (reqId === scrubReq.current) setScrubErr(String(e));
    } finally {
      if (reqId === scrubReq.current) setBusy(false);
    }
  }

  if (!jobId) {
    return (
      <div className="empty">
        <div className="empty-kicker">Structure</div>
        <h3>No job selected</h3>
        <p className="hint">Select a completed job to compare the initial lattice with post-cascade dump frames.</p>
      </div>
    );
  }

  if (err && !before && !after && !busy) {
    return (
      <div className="alert alert-fail" role="alert">
        {err}
      </div>
    );
  }

  const afterMeta = afterFrames.length
    ? index?.frames.find((f) => f.index === afterFrames[afterIdx])
    : null;

  const loadingEmpty = busy && !before && !after;

  return (
    <div className="stack structure-panel">
      <div className="panel-head">
        <h2>Structure viewer</h2>
        <span className="chip">
          <span className="chip-k">frames</span>
          <span className="chip-v">{index?.n_frames ?? 0}</span>
        </span>
      </div>
      <p className="hint">
        Atom color = LAMMPS type
        {(before?.type_symbols || after?.type_symbols)
          ? ` (${(before?.type_symbols || after?.type_symbols || [])
              .map((s, i) => `${i + 1}=${s}`)
              .join(", ")})`
          : ""}
        . Drag to rotate. Large cells are stride-sampled for interactive viewing; use OVITO for production analysis.
      </p>
      {(before?.type_symbols || after?.type_symbols) && (
        <div className="chip-row">
          {(before?.type_symbols || after?.type_symbols || []).map((s, i) => (
            <span className="chip" key={`${s}-${i}`}>
              <span className="chip-k">type {i + 1}</span>
              <span className="chip-v">{s}</span>
            </span>
          ))}
        </div>
      )}
      {err && (
        <div className="alert alert-fail" role="alert">
          {err}
        </div>
      )}
      {scrubErr && (
        <div className="alert alert-warn" role="status">
          Failed to load frame: {scrubErr}
        </div>
      )}
      {busy && <p className="hint">Loading frame…</p>}
      {loadingEmpty ? (
        <div className="empty">
          <div className="empty-kicker">Structure</div>
          <h3>Loading trajectory…</h3>
          <p className="hint">Fetching before/after frames for this job.</p>
        </div>
      ) : (
        <div className="structure-compare">
          <div className="stack">
            <h3>Before</h3>
            <div className="chip-row">
              <span className="chip">
                <span className="chip-k">step</span>
                <span className="chip-v">{before?.timestep ?? "—"}</span>
              </span>
              <span className="chip">
                <span className="chip-k">atoms</span>
                <span className="chip-v">
                  {before
                    ? `${before.n_atoms.toLocaleString()} / ${before.n_atoms_full.toLocaleString()}${
                        before.truncated ? " shown" : ""
                      }`
                    : "—"}
                </span>
              </span>
            </div>
            {before ? (
              <StructureAtomCanvas atoms={before.atoms} box={before.box} label="Initial lattice" />
            ) : (
              <div className="viz structure-viz empty-viz">No initial dump file</div>
            )}
          </div>
          <div className="stack">
            <h3>After</h3>
            <div className="chip-row">
              <span className="chip">
                <span className="chip-k">step</span>
                <span className="chip-v">{after?.timestep ?? "—"}</span>
              </span>
              <span className="chip">
                <span className="chip-k">atoms</span>
                <span className="chip-v">
                  {after
                    ? `${after.n_atoms.toLocaleString()} / ${after.n_atoms_full.toLocaleString()}${
                        after.truncated ? " shown" : ""
                      }`
                    : "—"}
                </span>
              </span>
              {afterMeta && (
                <span className="chip">
                  <span className="chip-k">file</span>
                  <span className="chip-v">{afterMeta.file}</span>
                </span>
              )}
            </div>
            {after ? (
              <StructureAtomCanvas atoms={after.atoms} box={after.box} label="Post-cascade lattice" />
            ) : (
              <div className="viz structure-viz empty-viz">No cascade dump file</div>
            )}
            {afterFrames.length > 1 && (
              <label className="scrubber">
                <span>
                  Timestep index {afterIdx + 1} / {afterFrames.length}
                  {after ? ` · t = ${after.timestep}` : ""}
                </span>
                <input
                  type="range"
                  min={0}
                  max={afterFrames.length - 1}
                  value={afterIdx}
                  onChange={(e) => void scrub(Number(e.target.value))}
                  aria-label="Trajectory timestep"
                />
              </label>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
