import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import StructureViewer from "./StructureViewer";

type ElementFraction = { symbol: string; atomic_percent: number };
type Material = {
  id: string;
  name: string;
  description: string;
  crystal: string;
  lattice_constant_A: number;
  lattice_c_A?: number | null;
  c_over_a?: number | null;
  composition: ElementFraction[];
  tags: string[];
  metadata_only?: boolean;
};
type CrystalInfo = {
  id: string;
  label: string;
  atoms_per_cell: number;
  needs_c: boolean;
  supported: boolean;
  interstitial_geometries: string[];
  default_interstitial_geometry: string;
  default_interstitial_direction: string;
  orients: Array<{ id: string; label: string }>;
  notes: string;
  sublattices?: string[];
};
type Potential = {
  id: string;
  name: string;
  elements: string[];
  recommended_for: string[];
  warnings: string[];
  available: boolean;
  is_placeholder?: boolean;
  source: string;
  lammps_pair_style: string;
  citation?: string;
  doi?: string;
  source_url?: string;
  formalism?: string;
  file_path?: string | null;
  library_id?: string | null;
};
type PotentialLibraryEntry = {
  id: string;
  name: string;
  elements: string[];
  pair_style: string;
  formalism: string;
  source: string;
  entry_url: string;
  download_url?: string | null;
  filename?: string | null;
  citation: string;
  doi: string;
  recommended_for: string[];
  warnings: string[];
  maps_to_catalog_id?: string | null;
  downloadable: boolean;
  installed: boolean;
};
type Scenario = {
  id: string;
  fuel: string;
  label: string;
  description: string;
  defaults: Record<string, unknown>;
};
type EngineStatus = {
  lammps_found: boolean;
  lammps_path?: string;
  lammps_version?: string;
  kart_found: boolean;
  kart_root?: string;
  kart_binary?: string;
  kart_commit_expected: string;
  kart_message: string;
  mmonca_found?: boolean;
  mmonca_path?: string;
  mmonca_message?: string;
  ase_found?: boolean;
  ase_message?: string;
  ovito_found?: boolean;
  ovito_path?: string;
  ovito_message?: string;
  ovito_mode?: string;
  ovito_version?: string | null;
  atomsk_found?: boolean;
  atomsk_path?: string;
};
type JobInfo = {
  id: string;
  status: string;
  project_name: string;
  material_id: string;
  potential_id: string;
  scenario_id: string;
  created_at: string;
  updated_at: string;
  message: string;
  run_params: RunParams;
  run_kart_anneal: boolean;
  run_mmonca_okmc?: boolean;
  defect_summary?: Record<string, number | string | object>;
  kart_summary?: Record<string, unknown>;
  mmonca_summary?: Record<string, unknown>;
  surface_summary?: Record<string, unknown>;
};
type RunParams = {
  mode: string;
  nx: number;
  ny: number;
  nz: number;
  boundary: string;
  crystal_orient: string;
  seed: number;
  ensemble: string;
  temperature_K: number;
  damp_ps: number;
  pka_species: string;
  pka_energy_eV: number;
  pka_direction: string;
  n_pkas: number;
  pka_delay_steps: number;
  pka_site: string;
  pka_frac_x: number;
  pka_frac_y: number;
  pka_frac_z: number;
  cascade_auto_stages: boolean;
  ion_type: string;
  ion_energy_eV: number;
  ion_count: number;
  ion_angle_deg: number;
  vacuum_layers: number;
  surface_fluence_ions: number;
  interstitial_species: string;
  interstitial_count: number;
  interstitial_direction: string;
  interstitial_geometry: string;
  interstitial_offset_A: number | null;
  interstitial_energy_eV: number;
  structure_kind: string;
  poly_n_grains: number;
  poly_seed: number;
  poly_texture: string;
  timestep_fs: number;
  max_steps: number;
  neighbor_skin: number;
  thermo_every: number;
  dump_every: number;
  dump_style: string;
  restart_every: number;
  ws_lattice_A: number | null;
  cluster_cutoff_A: number;
  confirm_large: boolean;
  run_dxa: boolean;
};

type TabId = "projects" | "doe" | "material" | "potential" | "scenario" | "params" | "run" | "results" | "engines";

const TABS: { id: TabId; step: string; label: string }[] = [
  { id: "projects", step: "01", label: "Projects" },
  { id: "doe", step: "02", label: "DOE" },
  { id: "material", step: "03", label: "Material" },
  { id: "potential", step: "04", label: "Potential" },
  { id: "scenario", step: "05", label: "Scenario" },
  { id: "params", step: "06", label: "LAMMPS" },
  { id: "run", step: "07", label: "Run" },
  { id: "results", step: "08", label: "Results" },
  { id: "engines", step: "09", label: "Engines" },
];

const PAIR_STYLE_WHITELIST = [
  "eam",
  "eam/alloy",
  "eam/fs",
  "meam",
  "snap",
  "table",
  "hybrid",
  "hybrid/overlay",
];

const defaultParams: RunParams = {
  mode: "cascade",
  nx: 8,
  ny: 8,
  nz: 8,
  boundary: "p p p",
  crystal_orient: "100",
  seed: 592856,
  ensemble: "nve",
  temperature_K: 300,
  damp_ps: 0.1,
  pka_species: "W",
  pka_energy_eV: 10000,
  pka_direction: "random",
  n_pkas: 1,
  pka_delay_steps: 0,
  pka_site: "center",
  pka_frac_x: 0.5,
  pka_frac_y: 0.5,
  pka_frac_z: 0.5,
  cascade_auto_stages: true,
  ion_type: "He",
  ion_energy_eV: 500,
  ion_count: 1,
  ion_angle_deg: 0,
  vacuum_layers: 4,
  surface_fluence_ions: 1,
  interstitial_species: "He",
  interstitial_count: 1,
  interstitial_direction: "111",
  interstitial_geometry: "octahedral",
  interstitial_offset_A: null,
  interstitial_energy_eV: 0,
  structure_kind: "single_crystal",
  poly_n_grains: 4,
  poly_seed: 42,
  poly_texture: "random",
  timestep_fs: 0.001,
  max_steps: 20000,
  neighbor_skin: 2,
  thermo_every: 100,
  dump_every: 1000,
  dump_style: "custom",
  restart_every: 0,
  ws_lattice_A: null,
  cluster_cutoff_A: 3.5,
  confirm_large: false,
  run_dxa: false,
};

function formatApiError(payload: unknown, fallback: string): string {
  if (typeof payload === "string") return payload || fallback;
  if (!payload || typeof payload !== "object") return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || typeof item !== "object") return String(item);
        const issue = item as { loc?: Array<string | number>; msg?: string };
        const path = issue.loc?.filter((part) => part !== "body").join(" → ");
        return `${path ? `${path}: ` : ""}${issue.msg || "Invalid value"}`;
      })
      .join(" · ");
  }
  return fallback;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const text = await res.text();
    let payload: unknown = text;
    try {
      payload = JSON.parse(text);
    } catch {
      /* Plain-text response. */
    }
    throw new Error(formatApiError(payload, `${res.status} ${res.statusText}`));
  }
  return res.json() as Promise<T>;
}

function normalizeComposition(rows: ElementFraction[]): ElementFraction[] {
  const total = rows.reduce((sum, row) => sum + Math.max(0, Number(row.atomic_percent) || 0), 0);
  if (total <= 0) throw new Error("Composition must contain a positive atomic fraction.");
  return rows.map((row) => ({
    symbol: row.symbol.trim(),
    atomic_percent: (Math.max(0, Number(row.atomic_percent) || 0) / total) * 100,
  }));
}

/** Prefer UI override, then catalog c, then a × c/a — never wipe a good catalog c with null. */
function resolveLatticeC(m: Material | null | undefined, override: number | null, a?: number): number | null {
  if (override != null && Number.isFinite(override) && override > 0) return override;
  if (m?.lattice_c_A != null && m.lattice_c_A > 0) return m.lattice_c_A;
  const a0 = a ?? m?.lattice_constant_A;
  if (m?.c_over_a != null && m.c_over_a > 0 && a0 != null && a0 > 0) return a0 * m.c_over_a;
  return null;
}

const ATOMIC_MASS: Record<string, number> = {
  H: 1.008,
  D: 2.014,
  He: 4.0026,
  C: 12.011,
  V: 50.942,
  Cr: 51.996,
  Fe: 55.845,
  Mo: 95.95,
  Ta: 180.95,
  W: 183.84,
  Re: 186.21,
};

function massOf(symbol: string): number {
  return ATOMIC_MASS[symbol.trim()] || 1;
}

/** Convert stored at% rows into editable wt% display values. */
function atToWt(rows: ElementFraction[]): number[] {
  const masses = rows.map((r) => (Number(r.atomic_percent) || 0) * massOf(r.symbol));
  const total = masses.reduce((s, m) => s + m, 0) || 1;
  return masses.map((m) => (m / total) * 100);
}

/** Apply an edited wt% value at index and return new at% composition. */
function wtEditToAt(rows: ElementFraction[], idx: number, wtValue: number): ElementFraction[] {
  const wts = atToWt(rows);
  wts[idx] = Math.max(0, wtValue);
  const moles = rows.map((r, i) => wts[i] / massOf(r.symbol));
  const total = moles.reduce((s, m) => s + m, 0) || 1;
  return rows.map((r, i) => ({
    symbol: r.symbol,
    atomic_percent: (moles[i] / total) * 100,
  }));
}

function Field({
  label,
  unit,
  children,
  htmlFor,
}: {
  label: string;
  unit?: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <label htmlFor={htmlFor}>
      <span>
        {label}
        {unit ? <span className="unit"> · {unit}</span> : null}
      </span>
      {children}
    </label>
  );
}

function DefectViz({ points }: { points: Array<{ x: number; y: number; z: number; kind: string }> }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x07090d);
    const camera = new THREE.PerspectiveCamera(45, el.clientWidth / Math.max(el.clientHeight, 1), 0.1, 1000);
    camera.position.set(12, 10, 16);
    camera.lookAt(0, 0, 0);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);
    const light = new THREE.DirectionalLight(0xffffff, 1.05);
    light.position.set(5, 10, 7);
    scene.add(light);
    scene.add(new THREE.AmbientLight(0x6688aa, 0.35));

    const group = new THREE.Group();
    for (const p of points.slice(0, 2000)) {
      const color = p.kind === "vacancy" ? 0xd46555 : p.kind === "interstitial" ? 0xd4894a : 0x3d9a6a;
      const geo = new THREE.SphereGeometry(0.12, 10, 10);
      const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.45, metalness: 0.2 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(p.x - 4, p.y - 4, p.z - 4);
      group.add(mesh);
    }
    scene.add(group);
    let frame = 0;
    let alive = true;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const animate = () => {
      if (!alive) return;
      frame = requestAnimationFrame(animate);
      if (!reduce) group.rotation.y += 0.004;
      renderer.render(scene, camera);
    };
    animate();
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      renderer.dispose();
      el.innerHTML = "";
    };
  }, [points]);
  return <div className="viz" ref={ref} role="img" aria-label="3D defect point cloud" />;
}

type KartEvent = { event: number; barrier_eV: number; time_s?: number; source?: string };
type KartRun = {
  temperature_K: number;
  status: string;
  message?: string;
  events?: KartEvent[];
  handoff?: string;
};
type KartSummary = {
  status?: string;
  message?: string;
  doe?: boolean;
  temperatures_K?: number[];
  events?: KartEvent[];
  runs?: KartRun[];
  handoff?: string;
};

type DoeCampaign = {
  id: string;
  name: string;
  status: string;
  message: string;
  axis_x: string;
  values_x: number[];
  axis_y?: string | null;
  values_y?: number[] | null;
  job_ids: string[];
  summary_rows: Array<Record<string, unknown>>;
  cases: Array<{ job_id?: string | null; label: string; status: string; overrides: Record<string, unknown> }>;
};

function KartTimeline({ events, label }: { events: KartEvent[]; label: string }) {
  if (!events.length) {
    return <p className="hint">No anneal events yet.</p>;
  }
  const maxB = Math.max(...events.map((e) => e.barrier_eV), 0.1);
  return (
    <div className="stack">
      <p className="hint">{label}</p>
      <div className="kart-timeline" role="img" aria-label="KART barrier timeline">
        {events.slice(0, 60).map((e) => (
          <div
            key={e.event}
            className="kart-bar"
            style={{ height: `${(e.barrier_eV / maxB) * 100}%` }}
            title={`#${e.event} · ${e.barrier_eV.toFixed(3)} eV · t=${e.time_s ?? "—"}`}
          />
        ))}
      </div>
      <div className="chip-row">
        <span className="chip">
          <span className="chip-k">events</span>
          <span className="chip-v">{events.length}</span>
        </span>
        <span className="chip">
          <span className="chip-k">Ē_bar</span>
          <span className="chip-v">
            {(events.reduce((s, e) => s + e.barrier_eV, 0) / events.length).toFixed(3)} eV
          </span>
        </span>
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<TabId>("projects");
  const [materials, setMaterials] = useState<Material[]>([]);
  const [potentials, setPotentials] = useState<Potential[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [engines, setEngines] = useState<EngineStatus | null>(null);
  const [materialId, setMaterialId] = useState("w-pure");
  const [composition, setComposition] = useState<ElementFraction[]>([{ symbol: "W", atomic_percent: 100 }]);
  const [lattice, setLattice] = useState(3.165);
  const [latticeC, setLatticeC] = useState<number | null>(null);
  const [crystals, setCrystals] = useState<CrystalInfo[]>([]);
  const [dxaSummary, setDxaSummary] = useState<Record<string, unknown> | null>(null);
  const [potentialId, setPotentialId] = useState("");
  const [scenarioId, setScenarioId] = useState("dt-divertor");
  const [params, setParams] = useState<RunParams>(defaultParams);
  const [projectName, setProjectName] = useState("W-He study");
  const [runKart, setRunKart] = useState(false);
  const [runMmonca, setRunMmonca] = useState(false);
  const [kartTemperatureK, setKartTemperatureK] = useState(600);
  const [kartMaxEvents, setKartMaxEvents] = useState(1000);
  const [kartMaxWallS, setKartMaxWallS] = useState(600);
  const [kartMaxKmcTimeS, setKartMaxKmcTimeS] = useState(1);
  const [kartDoeTemps, setKartDoeTemps] = useState("");
  const [kartSummary, setKartSummary] = useState<KartSummary | null>(null);
  const [cascadeTimeline, setCascadeTimeline] = useState<{
    auto?: boolean;
    note?: string;
    total_steps?: number;
    extended_max_steps?: boolean;
    stages?: Array<{
      id: string;
      label: string;
      steps: number;
      dump_every: number;
      timestep_start?: number;
      timestep_end?: number;
    }>;
  } | null>(null);
  const [campaigns, setCampaigns] = useState<DoeCampaign[]>([]);
  const [campaign, setCampaign] = useState<DoeCampaign | null>(null);
  const [doeName, setDoeName] = useState("DEMO-energy-T");
  const [doeAxisX, setDoeAxisX] = useState("pka_energy_eV");
  const [doeValuesX, setDoeValuesX] = useState("5000,10000,20000");
  const [doeAxisY, setDoeAxisY] = useState("temperature_K");
  const [doeValuesY, setDoeValuesY] = useState("300,600,800");
  const [doeLocal, setDoeLocal] = useState(true);
  const [hpcScheduler, setHpcScheduler] = useState("slurm");
  const [hpcCores, setHpcCores] = useState(8);
  const [hpcWalltime, setHpcWalltime] = useState("04:00:00");
  const [job, setJob] = useState<JobInfo | null>(null);
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [log, setLog] = useState("");
  const [defects, setDefects] = useState<{
    summary?: Record<string, unknown>;
    points?: Array<{ x: number; y: number; z: number; kind: string }>;
    clusters?: Array<{ size: number }>;
  } | null>(null);
  const [error, setError] = useState("");
  const [uploadName, setUploadName] = useState("");
  const [uploadElements, setUploadElements] = useState("W");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadPairStyle, setUploadPairStyle] = useState("eam/alloy");
  const [uploadAttachTo, setUploadAttachTo] = useState(true);
  const [library, setLibrary] = useState<PotentialLibraryEntry[]>([]);
  const [libQuery, setLibQuery] = useState("");
  const [libSource, setLibSource] = useState("");
  const [importUrl, setImportUrl] = useState("");
  const [entryUrl, setEntryUrl] = useState("");
  const [entryFiles, setEntryFiles] = useState<Array<{ filename: string; download_url: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [compUnit, setCompUnit] = useState<"at%" | "wt%">("at%");
  const [projectFilter, setProjectFilter] = useState<string>("");
  const loadJobReq = useRef(0);
  const modeDirty = useRef(false);

  const material = useMemo(() => materials.find((m) => m.id === materialId), [materials, materialId]);
  const selectedPot = useMemo(() => potentials.find((p) => p.id === potentialId), [potentials, potentialId]);
  const scenario = useMemo(() => scenarios.find((s) => s.id === scenarioId), [scenarios, scenarioId]);
  const projectNames = useMemo(() => {
    const names = new Set<string>();
    for (const j of jobs) {
      if (j.project_name) names.add(j.project_name);
    }
    if (projectName) names.add(projectName);
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [jobs, projectName]);
  const projectJobs = useMemo(() => {
    const key = projectFilter || projectName;
    if (!key) return jobs;
    return jobs.filter((j) => j.project_name === key);
  }, [jobs, projectFilter, projectName]);

  const compositionTotal = composition.reduce((s, e) => s + Number(e.atomic_percent || 0), 0);
  const cellVolume = params.nx * params.ny * params.nz;
  const largeCell = cellVolume > 20 * 20 * 20;
  const potIsDemo = Boolean(selectedPot?.is_placeholder);
  const crystalInfo = useMemo(
    () => crystals.find((c) => c.id === (material?.crystal || "").toLowerCase()) || null,
    [crystals, material?.crystal],
  );
  const RUNNABLE_CRYSTALS = useMemo(() => new Set(["bcc", "fcc", "hcp", "diamond", "hex"]), []);
  const atomsPerCell = useMemo(() => {
    if (crystalInfo) return crystalInfo.atoms_per_cell;
    const cry = (material?.crystal || "bcc").toLowerCase();
    return ({ bcc: 2, fcc: 4, hcp: 2, diamond: 8, hex: 2 } as Record<string, number>)[cry] ?? 2;
  }, [crystalInfo, material?.crystal]);
  const crystalSupported = crystalInfo
    ? crystalInfo.supported
    : RUNNABLE_CRYSTALS.has((material?.crystal || "bcc").toLowerCase());

  const intDirectionOptions = useMemo(() => {
    const orients = (crystalInfo?.orients || []).map((o) => o.id);
    const fallback = ["100", "110", "111"];
    const base = orients.length ? orients : fallback;
    const d = crystalInfo?.default_interstitial_direction;
    const ids = [...new Set([...base, ...(d ? [d] : []), "random"])];
    return ids;
  }, [crystalInfo]);

  const effectiveLatticeC = useMemo(
    () => resolveLatticeC(material, latticeC, lattice),
    [material, latticeC, lattice],
  );

  const blockers = useMemo(() => {
    const list: string[] = [];
    if (!potentialId) list.push("Select a potential");
    if (selectedPot && !selectedPot.available && !selectedPot.is_placeholder) {
      list.push("Potential file missing — upload or place under data/potentials/curated/");
    }
    if (compositionTotal <= 0) list.push("Composition requires a positive atomic fraction");
    if (largeCell && !params.confirm_large) list.push("Large cell (>20³) — confirm in LAMMPS tab");
    if (material?.metadata_only) list.push("Material is metadata-only (no runnable lattice recipe)");
    if (material && !crystalSupported && !selectedPot?.is_placeholder) {
      list.push(`Crystal ${material.crystal} needs a placeholder/dry-run potential or a supported lattice`);
    }
    const needsC =
      crystalInfo?.needs_c ||
      ["hcp", "hex"].includes((material?.crystal || "").toLowerCase());
    if (needsC && !(effectiveLatticeC != null && effectiveLatticeC > 0)) {
      list.push("HCP/hex materials need a positive lattice c");
    }
    if (params.mode === "interstitial" && selectedPot) {
      const need = new Set(
        [
          ...composition.filter((e) => e.atomic_percent > 0).map((e) => e.symbol),
          params.interstitial_species,
        ].filter(Boolean),
      );
      if (![...need].every((s) => selectedPot.elements.includes(s))) {
        list.push(
          `Potential must cover host + interstitial species (${[...need].join(", ")}); current covers ${selectedPot.elements.join(" ")}`,
        );
      }
    }
    if (selectedPot && ["cascade", "implant", "surface"].includes(params.mode)) {
      const need = new Set(
        [
          ...composition.filter((e) => e.atomic_percent > 0).map((e) => e.symbol),
          params.mode === "cascade" ? params.pka_species : params.ion_type,
        ].filter(Boolean),
      );
      if (![...need].every((s) => selectedPot.elements.includes(s))) {
        list.push(
          `Potential must cover host + ${params.mode === "cascade" ? "PKA" : "ion"} species (${[...need].join(", ")}); current covers ${selectedPot.elements.join(" ")}`,
        );
      }
    }
    return list;
  }, [
    potentialId,
    selectedPot,
    compositionTotal,
    largeCell,
    params.confirm_large,
    params.mode,
    params.interstitial_species,
    params.pka_species,
    params.ion_type,
    composition,
    material,
    crystalSupported,
    crystalInfo,
    latticeC,
    effectiveLatticeC,
  ]);

  const verdict = blockers.length
    ? { tone: "blocked" as const, label: "Blocked", msg: blockers[0] }
    : potIsDemo || !engines?.lammps_found || !crystalSupported
      ? {
          tone: "warn" as const,
          label: "Ready · dry-run",
          msg: !crystalSupported
            ? `Crystal ${material?.crystal} — dry-run demo only until supported.`
            : potIsDemo
              ? "Placeholder potential — demo dumps only. Upload a published potential for real MD."
              : "LAMMPS not on PATH — job will write demo dumps for pipeline testing.",
        }
      : { tone: "ready" as const, label: "Ready", msg: "Material, potential, and parameters look runnable." };

  useEffect(() => {
    Promise.all([
      api<{ status: string }>("/api/health"),
      api<Material[]>("/api/materials"),
      api<Scenario[]>("/api/scenarios"),
      api<EngineStatus>("/api/engines/status"),
      api<JobInfo[]>("/api/jobs"),
      api<DoeCampaign[]>("/api/campaigns").catch(() => [] as DoeCampaign[]),
      api<{ crystals: CrystalInfo[] }>("/api/crystals").catch(() => ({ crystals: [] as CrystalInfo[] })),
    ])
      .then(([, m, s, e, history, camps, cry]) => {
        setMaterials(m);
        setScenarios(s);
        setEngines(e);
        setJobs(history);
        setCampaigns(camps);
        setCrystals(cry.crystals || []);
        const active = camps.find((c) => ["queued", "running"].includes(c.status));
        if (active) setCampaign(active);
        const first = m.find((x) => x.id === "w-pure") || m[0];
        if (first) {
          setMaterialId(first.id);
          setComposition(first.composition);
          setLattice(first.lattice_constant_A);
          setLatticeC(resolveLatticeC(first, null));
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  // Keep crystal-dependent selects in sync with the active crystal registry entry
  useEffect(() => {
    if (!crystalInfo) return;
    setParams((p) => {
      let next = p;
      const orientOk = crystalInfo.orients.some((o) => o.id === p.crystal_orient);
      if (!orientOk) {
        next = { ...next, crystal_orient: crystalInfo.orients[0]?.id || "100" };
      }
      const geomOk = crystalInfo.interstitial_geometries.includes(p.interstitial_geometry);
      if (!geomOk) {
        next = { ...next, interstitial_geometry: crystalInfo.default_interstitial_geometry };
      }
      const allowedDirs = new Set([
        ...crystalInfo.orients.map((o) => o.id),
        crystalInfo.default_interstitial_direction,
        "random",
      ]);
      const isNamed =
        ["100", "110", "111", "basal", "c", "prism", "random"].includes(p.interstitial_direction);
      if (isNamed && !allowedDirs.has(p.interstitial_direction)) {
        next = { ...next, interstitial_direction: crystalInfo.default_interstitial_direction };
      }
      return next;
    });
  }, [crystalInfo]);

  useEffect(() => {
    if (!materialId) return;
    api<Potential[]>(`/api/potentials?material_id=${materialId}`)
      .then((p) => {
        setPotentials(p);
        const avail = p.find((x) => x.available) || p.find((x) => x.is_placeholder) || p[0];
        setPotentialId(avail?.id || "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    const qs = new URLSearchParams({ material_id: materialId });
    if (libQuery) qs.set("q", libQuery);
    if (libSource) qs.set("source", libSource);
    api<PotentialLibraryEntry[]>(`/api/potentials/library?${qs}`)
      .then(setLibrary)
      .catch(() => setLibrary([]));
  }, [materialId]);

  useEffect(() => {
    if (tab !== "potential" || !materialId) return;
    const handle = window.setTimeout(() => {
      const qs = new URLSearchParams({ material_id: materialId });
      if (libQuery) qs.set("q", libQuery);
      if (libSource) qs.set("source", libSource);
      api<PotentialLibraryEntry[]>(`/api/potentials/library?${qs}`)
        .then(setLibrary)
        .catch(() => setLibrary([]));
    }, 200);
    return () => window.clearTimeout(handle);
  }, [tab, materialId, libQuery, libSource]);

  useEffect(() => {
    const sc = scenarios.find((s) => s.id === scenarioId);
    if (!sc) return;
    setParams((prev) => {
      const defaults = { ...(sc.defaults as Partial<RunParams>) };
      if (modeDirty.current) {
        delete defaults.mode;
        delete defaults.boundary;
      }
      return { ...prev, ...defaults } as RunParams;
    });
  }, [scenarioId, scenarios]);

  useEffect(() => {
    if (tab !== "engines") return;
    api<EngineStatus>("/api/engines/status")
      .then(setEngines)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [tab]);

  useEffect(() => {
    if (!job) return;
    const watchedId = job.id;
    let cancelled = false;
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${wsProto}://${location.host}/api/jobs/${watchedId}/log`);
    ws.onmessage = (ev) => {
      if (!cancelled) setLog((prev) => prev + ev.data);
    };
    const timer = setInterval(async () => {
      try {
        const info = await api<JobInfo>(`/api/jobs/${watchedId}`);
        if (cancelled) return;
        setJob((prev) => (prev?.id === watchedId ? info : prev));
        setJobs((history) => [info, ...history.filter((item) => item.id !== info.id)]);
        if (!["completed", "failed", "cancelled"].includes(info.status)) return;
        clearInterval(timer);
        if (info.status === "completed" || info.status === "failed") {
          try {
            const d = await api<NonNullable<typeof defects>>(`/api/jobs/${watchedId}/defects`);
            if (!cancelled) setDefects(d);
          } catch {
            /* defects may be absent on early failure */
          }
          try {
            const ks = await api<KartSummary>(`/api/jobs/${watchedId}/kart`);
            if (!cancelled) setKartSummary(ks);
          } catch {
            if (!cancelled) setKartSummary((info.kart_summary as KartSummary) || null);
          }
          try {
            const tl = await api<{
              stages?: Array<{
                id: string;
                label: string;
                steps: number;
                dump_every: number;
                timestep_start?: number;
                timestep_end?: number;
              }>;
              note?: string;
              total_steps?: number;
              extended_max_steps?: boolean;
            }>(`/api/jobs/${watchedId}/cascade-timeline`);
            if (!cancelled) setCascadeTimeline(tl);
          } catch {
            if (!cancelled) setCascadeTimeline(null);
          }
          try {
            const dxa = await api<Record<string, unknown>>(`/api/jobs/${watchedId}/dxa`);
            if (!cancelled) setDxaSummary(dxa);
          } catch {
            if (!cancelled) setDxaSummary(null);
          }
          if (!cancelled && info.status === "completed") {
            setTab((t) => (t === "run" ? "results" : t));
          }
        }
      } catch {
        /* ignore transient poll errors */
      }
    }, 1000);
    return () => {
      cancelled = true;
      ws.close();
      clearInterval(timer);
    };
  }, [job?.id]);

  useEffect(() => {
    if (!campaign?.id) return;
    if (!["queued", "running"].includes(campaign.status)) return;
    const timer = setInterval(() => {
      void refreshCampaign(campaign.id).catch(() => undefined);
    }, 2000);
    return () => clearInterval(timer);
  }, [campaign?.id, campaign?.status]);

  const doePreview = useMemo(() => {
    const xs = parseNumList(doeValuesX);
    const ys = doeAxisY ? parseNumList(doeValuesY) : [null];
    const raw = Math.max(0, xs.length) * Math.max(1, ys.length);
    const capped = Math.min(raw, 12);
    return { xs: xs.length, ys: doeAxisY ? ys.length : 0, raw, capped, truncated: raw > 12 };
  }, [doeValuesX, doeValuesY, doeAxisY]);

  const campaignProgress = useMemo(() => {
    if (!campaign) return null;
    const cases = campaign.cases;
    const total = cases.length;
    const done = cases.filter((c) =>
      ["completed", "failed", "cancelled", "export_ready"].includes(c.status),
    ).length;
    const failed = cases.filter((c) => c.status === "failed").length;
    const running = cases.filter((c) =>
      ["running", "analyzing", "annealing", "queued"].includes(c.status),
    ).length;
    return { total, done, failed, running };
  }, [campaign]);

  async function loadJob(jobId: string) {
    if (!jobId) return;
    const reqId = ++loadJobReq.current;
    setBusy(true);
    setError("");
    setLog("");
    setDefects(null);
    setKartSummary(null);
    setCascadeTimeline(null);
    setDxaSummary(null);
    try {
      const info = await api<JobInfo>(`/api/jobs/${jobId}`);
      if (reqId !== loadJobReq.current) return;
      setJob(info);
      if (info.status === "completed" || info.status === "failed") {
        try {
          const d = await api<NonNullable<typeof defects>>(`/api/jobs/${jobId}/defects`);
          if (reqId === loadJobReq.current) setDefects(d);
        } catch {
          /* defects may be missing */
        }
        try {
          const ks = await api<KartSummary>(`/api/jobs/${jobId}/kart`);
          if (reqId === loadJobReq.current) setKartSummary(ks);
        } catch {
          if (reqId === loadJobReq.current) setKartSummary((info.kart_summary as KartSummary) || null);
        }
        try {
          const tl = await api(`/api/jobs/${jobId}/cascade-timeline`);
          if (reqId === loadJobReq.current) setCascadeTimeline(tl);
        } catch {
          if (reqId === loadJobReq.current) setCascadeTimeline(null);
        }
        try {
          const dxa = await api(`/api/jobs/${jobId}/dxa`);
          if (reqId === loadJobReq.current) setDxaSummary(dxa);
        } catch {
          if (reqId === loadJobReq.current) setDxaSummary(null);
        }
      }
    } catch (err) {
      if (reqId === loadJobReq.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (reqId === loadJobReq.current) setBusy(false);
    }
  }

  function setParam<K extends keyof RunParams>(key: K, value: RunParams[K]) {
    setParams((p) => ({ ...p, [key]: value }));
  }

  async function saveComposition() {
    if (!material) return;
    setBusy(true);
    setError("");
    try {
      const normalized = normalizeComposition(composition);
      const updated = await api<Material>(`/api/materials/${material.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          composition: normalized,
          lattice_constant_A: lattice,
          lattice_c_A: resolveLatticeC(material, latticeC, lattice),
          crystal: material.crystal,
        }),
      });
      setComposition(updated.composition);
      setMaterials((ms) => ms.map((m) => (m.id === updated.id ? updated : m)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function refreshPotentials(selectId?: string) {
    const p = await api<Potential[]>(`/api/potentials?material_id=${materialId}`);
    setPotentials(p);
    if (selectId) setPotentialId(selectId);
    const qs = new URLSearchParams({ material_id: materialId });
    if (libQuery) qs.set("q", libQuery);
    if (libSource) qs.set("source", libSource);
    setLibrary(await api<PotentialLibraryEntry[]>(`/api/potentials/library?${qs}`).catch(() => []));
  }

  async function uploadPotential() {
    if (!uploadFile) return;
    setBusy(true);
    setError("");
    try {
      const elems = uploadElements.split(/[\s,]+/).filter(Boolean);
      const shouldAttach = Boolean(
        uploadAttachTo && selectedPot && (!selectedPot.available || selectedPot.is_placeholder),
      );
      const meta = {
        name: uploadName || uploadFile.name,
        formalism: uploadPairStyle.startsWith("eam")
          ? uploadPairStyle
          : uploadPairStyle === "meam"
            ? "meam"
            : uploadPairStyle === "snap"
              ? "snap"
              : uploadPairStyle === "table"
                ? "table"
                : "other",
        elements: elems,
        lammps_pair_style: uploadPairStyle,
        pair_coeff_template: `pair_coeff * * {file} ${elems.join(" ")}`,
        notes: "Uploaded via Aegis UI",
        recommended_for: ["cascade"],
        attach_to_id: shouldAttach ? selectedPot!.id : null,
      };
      const fd = new FormData();
      fd.append("file", uploadFile);
      fd.append("meta", JSON.stringify(meta));
      const pot = await api<Potential>("/api/potentials/upload", { method: "POST", body: fd });
      await refreshPotentials(pot.id);
      setUploadFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function downloadLibraryEntry(entry: PotentialLibraryEntry) {
    if (!entry.downloadable) return;
    setBusy(true);
    setError("");
    try {
      const pot = await api<Potential>("/api/potentials/library/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          library_id: entry.id,
          attach_to_id: entry.maps_to_catalog_id || undefined,
        }),
      });
      await refreshPotentials(pot.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function importDownloadUrl() {
    if (!importUrl.trim()) return;
    setBusy(true);
    setError("");
    try {
      const pot = await api<Potential>("/api/potentials/library/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: importUrl.trim(),
          attach_to_id:
            selectedPot && (!selectedPot.available || selectedPot.is_placeholder) ? selectedPot.id : undefined,
          elements: uploadElements.split(/[\s,]+/).filter(Boolean),
          lammps_pair_style: uploadPairStyle,
          name: uploadName || undefined,
        }),
      });
      await refreshPotentials(pot.id);
      setImportUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function scrapeNistEntry() {
    if (!entryUrl.trim()) return;
    setBusy(true);
    setError("");
    try {
      const res = await api<{ files: Array<{ filename: string; download_url: string }> }>(
        "/api/potentials/library/import-entry",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entry_url: entryUrl.trim() }),
        },
      );
      setEntryFiles(res.files || []);
      if (!res.files?.length) setError("No parameter files found on that NIST entry page.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function runJob() {
    if (blockers.length) {
      setError(blockers.join(" · "));
      return;
    }
    setBusy(true);
    setError("");
    setLog("");
    setDefects(null);
    setKartSummary(null);
    setCascadeTimeline(null);
    setDxaSummary(null);
    try {
      const normalized = normalizeComposition(composition);
      setComposition(normalized);
      const body = {
        project_name: projectName,
        material_id: materialId,
        material_override: material
          ? {
              ...material,
              composition: normalized,
              lattice_constant_A: lattice,
              lattice_c_A: resolveLatticeC(material, latticeC, lattice),
            }
          : undefined,
        potential_id: potentialId,
        scenario_id: scenarioId,
        run_params: params,
        run_kart_anneal: runKart,
        kart_temperature_K: kartTemperatureK,
        kart_max_events: kartMaxEvents,
        kart_max_wall_s: kartMaxWallS,
        kart_max_kmc_time_s: kartMaxKmcTimeS,
        kart_anneal_temperatures: (() => {
          const doe = kartDoeTemps
            .split(/[\s,]+/)
            .map((x) => Number(x))
            .filter((x) => Number.isFinite(x) && x > 0);
          return doe.length ? doe : null;
        })(),
        run_mmonca_okmc: runMmonca,
        mmonca_temperature_K: kartTemperatureK,
        mmonca_max_events: kartMaxEvents,
      };
      const info = await api<JobInfo>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setJob(info);
      setJobs((history) => [info, ...history.filter((item) => item.id !== info.id)]);
      setTab("run");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function cancelJob() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const cancelled = await api<JobInfo>(`/api/jobs/${job.id}/cancel`, { method: "POST" });
      setJob(cancelled);
      setJobs((history) => [cancelled, ...history.filter((item) => item.id !== cancelled.id)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function exportDefects() {
    if (!defects || !job) return;
    const blob = new Blob([JSON.stringify(defects, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `aegis-${job.id}-defects.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function reannealDoe() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const doe = kartDoeTemps
        .split(/[\s,]+/)
        .map((x) => Number(x))
        .filter((x) => Number.isFinite(x) && x > 0);
      const summary = await api<KartSummary>(`/api/jobs/${job.id}/kart/anneal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          temperature_K: kartTemperatureK,
          max_events: kartMaxEvents,
          max_wall_s: kartMaxWallS,
          max_kmc_time_s: kartMaxKmcTimeS,
          temperatures: doe.length ? doe : [kartTemperatureK],
        }),
      });
      setKartSummary(summary);
      const info = await api<JobInfo>(`/api/jobs/${job.id}`);
      setJob(info);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function parseNumList(raw: string): number[] {
    return raw
      .split(/[\s,]+/)
      .map((x) => Number(x))
      .filter((x) => Number.isFinite(x));
  }

  async function launchCampaign() {
    if (blockers.length) {
      setError(blockers.join(" · "));
      return;
    }
    const xs = parseNumList(doeValuesX);
    const ys = doeAxisY ? parseNumList(doeValuesY) : [];
    if (!xs.length) {
      setError("Axis X needs at least one numeric value");
      return;
    }
    if (doeAxisY && !ys.length) {
      setError("Axis Y needs at least one numeric value (or choose 1D sweep)");
      return;
    }
    if (doeAxisY && doeAxisX === doeAxisY) {
      setError("Axis X and Axis Y must differ");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const normalized = normalizeComposition(composition);
      setComposition(normalized);
      const body = {
        name: doeName || "doe-campaign",
        run_locally: doeLocal,
        axis_x: doeAxisX,
        values_x: xs,
        axis_y: doeAxisY || null,
        values_y: doeAxisY ? ys : null,
        max_jobs: 12,
        base: {
          project_name: projectName,
          material_id: materialId,
          material_override: material
            ? {
                ...material,
                composition: normalized,
                lattice_constant_A: lattice,
                lattice_c_A: resolveLatticeC(material, latticeC, lattice),
              }
            : undefined,
          potential_id: potentialId,
          scenario_id: scenarioId,
          run_params: params,
          run_kart_anneal: false,
          run_mmonca_okmc: false,
        },
      };
      const camp = await api<DoeCampaign>("/api/campaigns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setCampaign(camp);
      setCampaigns((cs) => [camp, ...cs.filter((c) => c.id !== camp.id)]);
      setTab("doe");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function refreshCampaign(id: string) {
    const camp = await api<DoeCampaign>(`/api/campaigns/${id}`);
    setCampaign(camp);
    setCampaigns((cs) => [camp, ...cs.filter((c) => c.id !== camp.id)]);
    const history = await api<JobInfo[]>("/api/jobs");
    setJobs(history);
  }

  async function exportHpc(kind: "job" | "campaign") {
    setBusy(true);
    setError("");
    try {
      const payload = {
        scheduler: hpcScheduler,
        cores: hpcCores,
        walltime: hpcWalltime || "04:00:00",
        lammps_bin: "lmp",
      };
      const path =
        kind === "job"
          ? `/api/jobs/${job?.id}/hpc-export`
          : `/api/campaigns/${campaign?.id}/hpc-export`;
      if (kind === "job" && !job?.id) throw new Error("Select a job first");
      if (kind === "campaign" && !campaign?.id) throw new Error("Select a campaign first");
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = kind === "job" ? `aegis-${job!.id}-hpc.zip` : `aegis-${campaign!.id}-hpc.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function campaignSummaryRows(c: DoeCampaign): Array<Record<string, unknown>> {
    if (c.summary_rows.length) return c.summary_rows;
    return c.cases.map((row) => ({ label: row.label, status: row.status, ...row.overrides, job_id: row.job_id }));
  }

  function summaryColumns(rows: Array<Record<string, unknown>>): string[] {
    const preferred = [
      "label",
      "status",
      "job_id",
      "pka_energy_eV",
      "ion_energy_eV",
      "temperature_K",
      "n_pkas",
      "ion_count",
      "surface_fluence_ions",
      "vacancies",
      "interstitials",
      "clusters",
      "mean_host_recession_A",
      "fuzz_atom_count",
    ];
    const keys = new Set<string>();
    for (const row of rows) {
      for (const k of Object.keys(row)) keys.add(k);
    }
    const ordered = preferred.filter((k) => keys.has(k));
    for (const k of keys) {
      if (!ordered.includes(k)) ordered.push(k);
    }
    return ordered;
  }

  function exportCampaignCsv() {
    if (!campaign) return;
    const rows = campaignSummaryRows(campaign);
    const cols = summaryColumns(rows);
    const esc = (v: unknown) => {
      const s = v == null ? "" : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aegis-${campaign.id}-doe.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const clusterSizes = defects?.clusters?.map((c) => c.size) || [];
  const maxCluster = Math.max(1, ...clusterSizes);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to main content
      </a>

      <header className="topbar">
        <div className="brand-block">
          <p className="eyebrow">PFM radiation damage workbench</p>
          <h1 className="brand">Aegis</h1>
          <p className="brand-sub">
            Cascade MD → defect analysis → optional k-ART. D–D / D–T are scenario presets, not plasma transport.
          </p>
        </div>
        <div className="kpi-row" aria-label="Engine status">
          <div className="kpi">
            <span className="kpi-k">LAMMPS</span>
            <span className={`kpi-v ${engines?.lammps_found ? "tone-ok" : "tone-warn"}`}>
              {engines?.lammps_found ? "found" : "dry-run"}
            </span>
          </div>
          <div className="kpi">
            <span className="kpi-k">KART</span>
            <span className={`kpi-v ${engines?.kart_found ? "tone-ok" : "tone-warn"}`}>
              {engines?.kart_found ? "found" : "stub"}
            </span>
          </div>
          <div className="kpi">
            <span className="kpi-k">Cell</span>
            <span className="kpi-v">
              {params.nx}×{params.ny}×{params.nz}
            </span>
          </div>
          <div className="kpi">
            <span className="kpi-k">Job</span>
            <span className="kpi-v">{job?.status || "idle"}</span>
          </div>
          <button
            type="button"
            className="primary-run"
            disabled={busy || blockers.length > 0}
            onClick={runJob}
            aria-label="Queue LAMMPS job"
          >
            {busy ? "Working…" : "Run job"}
          </button>
        </div>
      </header>

      <div className="verdict" role="status" aria-live="polite">
        <span className={`verdict-badge ${verdict.tone}`}>{verdict.label}</span>
        <span className="verdict-msg">{verdict.msg}</span>
        {blockers.length > 1 && (
          <span className="chip">
            <span className="chip-k">+</span>
            <span className="chip-v">{blockers.length - 1} more</span>
          </span>
        )}
      </div>

      <aside className="rail" aria-label="Workflow">
        <nav>
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? "active" : ""}
              onClick={() => setTab(t.id)}
              aria-current={tab === t.id ? "page" : undefined}
            >
              <span className="step">{t.step}</span>
              {t.label}
            </button>
          ))}
        </nav>
      </aside>

      <main id="main" className="main">
        {error && (
          <div className="alert alert-fail" role="alert">
            {error}
          </div>
        )}

        {tab === "projects" && (
          <section className="panel stack">
            <div className="panel-head">
              <h2>Projects</h2>
              <span className="chip">
                <span className="chip-k">jobs</span>
                <span className="chip-v">{jobs.length}</span>
              </span>
            </div>
            <p className="hint">
              Group runs by study name. Opening a job loads its status, log, and results without changing the current recipe
              until you re-run.
            </p>
            <div className="row">
              <Field label="Active project" htmlFor="proj-active">
                <input
                  id="proj-active"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="e.g. W-He divertor study"
                />
              </Field>
              <Field label="Filter history" htmlFor="proj-filter">
                <select
                  id="proj-filter"
                  value={projectFilter}
                  onChange={(e) => setProjectFilter(e.target.value)}
                >
                  <option value="">All projects</option>
                  {projectNames.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="row">
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setProjectName("untitled");
                  setProjectFilter("");
                  setJob(null);
                  setLog("");
                  setDefects(null);
                  setKartSummary(null);
                  setCascadeTimeline(null);
                  setDxaSummary(null);
                }}
              >
                New study
              </button>
              <button type="button" className="secondary" onClick={() => setTab("doe")}>
                Open DOE sweeps
              </button>
              <button type="button" className="secondary" onClick={() => setTab("material")}>
                Continue to Material
              </button>
            </div>
            <h3>Job history</h3>
            {projectJobs.length === 0 ? (
              <div className="empty">
                <div className="empty-kicker">No runs yet</div>
                <h3>Start a cascade</h3>
                <p className="hint">Configure material → potential → scenario → LAMMPS, then Run.</p>
              </div>
            ) : (
              <div className="stack">
                {projectJobs.slice(0, 40).map((j) => (
                  <button
                    key={j.id}
                    type="button"
                    className={`job-row ${job?.id === j.id ? "active" : ""}`}
                    onClick={() => {
                      void loadJob(j.id);
                      setProjectName(j.project_name);
                      setTab(j.status === "completed" || j.status === "failed" ? "results" : "run");
                    }}
                  >
                    <span className="mono">{j.id}</span>
                    <span>{j.project_name}</span>
                    <span className={`chip-v status-${j.status}`}>{j.status}</span>
                    <span className="hint">{j.created_at?.slice(0, 19)?.replace("T", " ")}</span>
                  </button>
                ))}
              </div>
            )}
            {job && (
              <div className="row">
                <Field label="HPC scheduler" htmlFor="hpc-sched-proj">
                  <select id="hpc-sched-proj" value={hpcScheduler} onChange={(e) => setHpcScheduler(e.target.value)}>
                    <option value="slurm">Slurm</option>
                    <option value="pbs">PBS</option>
                    <option value="none">files only</option>
                  </select>
                </Field>
                <Field label="Cores" htmlFor="hpc-cores-proj">
                  <input
                    id="hpc-cores-proj"
                    type="number"
                    value={hpcCores}
                    onChange={(e) => setHpcCores(Number(e.target.value))}
                  />
                </Field>
                <Field label="Walltime" unit="HH:MM:SS" htmlFor="hpc-wall-proj">
                  <input
                    id="hpc-wall-proj"
                    value={hpcWalltime}
                    onChange={(e) => setHpcWalltime(e.target.value)}
                  />
                </Field>
                <button type="button" className="secondary" disabled={busy} onClick={() => void exportHpc("job")}>
                  Export HPC pack
                </button>
              </div>
            )}
          </section>
        )}

        {tab === "doe" && (
          <section className="panel stack">
            <div className="panel-head">
              <h2>DEMO DOE sweeps</h2>
              <span className="chip">
                <span className="chip-k">campaigns</span>
                <span className="chip-v">{campaigns.length}</span>
              </span>
            </div>
            <p className="hint">
              Cartesian sweeps (energy × T, etc.) using the current Material / Potential / LAMMPS recipe as the base
              case. Local runs execute serially and auto-refresh; uncheck local to prepare inputs for an HPC zip.
            </p>
            <Field label="Campaign name" htmlFor="doe-name">
              <input id="doe-name" value={doeName} onChange={(e) => setDoeName(e.target.value)} />
            </Field>
            <div className="row">
              <Field label="Axis X" htmlFor="doe-ax">
                <select id="doe-ax" value={doeAxisX} onChange={(e) => setDoeAxisX(e.target.value)}>
                  <option value="pka_energy_eV">PKA energy (eV)</option>
                  <option value="ion_energy_eV">Ion energy (eV)</option>
                  <option value="temperature_K">Temperature (K)</option>
                  <option value="n_pkas">n PKAs</option>
                  <option value="ion_count">Ion count</option>
                  <option value="surface_fluence_ions">Surface fluence</option>
                  <option value="interstitial_count">Interstitial count</option>
                </select>
              </Field>
              <Field label="Values X" unit="comma-separated" htmlFor="doe-vx">
                <input id="doe-vx" value={doeValuesX} onChange={(e) => setDoeValuesX(e.target.value)} />
              </Field>
            </div>
            <div className="row">
              <Field label="Axis Y" htmlFor="doe-ay">
                <select id="doe-ay" value={doeAxisY} onChange={(e) => setDoeAxisY(e.target.value)}>
                  <option value="temperature_K">Temperature (K)</option>
                  <option value="pka_energy_eV">PKA energy (eV)</option>
                  <option value="ion_energy_eV">Ion energy (eV)</option>
                  <option value="">(none — 1D sweep)</option>
                </select>
              </Field>
              <Field label="Values Y" unit="comma-separated" htmlFor="doe-vy">
                <input id="doe-vy" value={doeValuesY} onChange={(e) => setDoeValuesY(e.target.value)} disabled={!doeAxisY} />
              </Field>
            </div>
            <div className="chip-row">
              <span className="chip">
                <span className="chip-k">matrix</span>
                <span className="chip-v">
                  {doePreview.xs}
                  {doeAxisY ? ` × ${doePreview.ys}` : ""} → {doePreview.capped} case
                  {doePreview.capped === 1 ? "" : "s"}
                  {doePreview.truncated ? ` (capped from ${doePreview.raw})` : ""}
                </span>
              </span>
              {campaignProgress && (
                <>
                  <span className="chip">
                    <span className="chip-k">done</span>
                    <span className="chip-v">
                      {campaignProgress.done}/{campaignProgress.total}
                    </span>
                  </span>
                  {campaignProgress.running > 0 && (
                    <span className="chip">
                      <span className="chip-k">active</span>
                      <span className="chip-v">{campaignProgress.running}</span>
                    </span>
                  )}
                  {campaignProgress.failed > 0 && (
                    <span className="chip">
                      <span className="chip-k">failed</span>
                      <span className="chip-v">{campaignProgress.failed}</span>
                    </span>
                  )}
                </>
              )}
            </div>
            <label className="check-row">
              <input type="checkbox" checked={doeLocal} onChange={(e) => setDoeLocal(e.target.checked)} />
              Run locally (serial queue)
            </label>
            <div className="row">
              <Field label="HPC scheduler" htmlFor="hpc-sched-doe">
                <select id="hpc-sched-doe" value={hpcScheduler} onChange={(e) => setHpcScheduler(e.target.value)}>
                  <option value="slurm">Slurm</option>
                  <option value="pbs">PBS</option>
                  <option value="none">files only</option>
                </select>
              </Field>
              <Field label="Cores" htmlFor="hpc-cores-doe">
                <input
                  id="hpc-cores-doe"
                  type="number"
                  value={hpcCores}
                  onChange={(e) => setHpcCores(Number(e.target.value))}
                />
              </Field>
              <Field label="Walltime" unit="HH:MM:SS" htmlFor="hpc-wall-doe">
                <input id="hpc-wall-doe" value={hpcWalltime} onChange={(e) => setHpcWalltime(e.target.value)} />
              </Field>
            </div>
            <div className="row">
              <button
                type="button"
                disabled={busy || blockers.length > 0 || doePreview.capped < 1}
                onClick={() => void launchCampaign()}
              >
                Launch DOE campaign
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy || !campaign}
                onClick={() => campaign && void refreshCampaign(campaign.id)}
              >
                Refresh summary
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy || !campaign}
                onClick={() => void exportHpc("campaign")}
              >
                Export campaign HPC zip
              </button>
              <button
                type="button"
                className="secondary"
                disabled={!campaign || campaignSummaryRows(campaign).length === 0}
                onClick={exportCampaignCsv}
              >
                Export CSV
              </button>
            </div>
            {blockers.length > 0 && (
              <div className="alert alert-warn">Fix readiness blockers before launching: {blockers[0]}</div>
            )}
            {!doeLocal && (
              <div className="alert alert-warn">
                Export-only mode prepares <code>in.aegis</code> for each case without running LAMMPS locally — download
                the HPC zip when ready.
              </div>
            )}
            <h3>Campaign history</h3>
            <div className="stack">
              {campaigns.length === 0 && <p className="hint">No campaigns yet.</p>}
              {campaigns.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`job-row ${campaign?.id === c.id ? "active" : ""}`}
                  onClick={() => void refreshCampaign(c.id)}
                >
                  <span className="mono">{c.id}</span>
                  <span>{c.name}</span>
                  <span className={`chip-v status-${c.status}`}>{c.status}</span>
                  <span className="hint">{c.message}</span>
                </button>
              ))}
            </div>
            {campaign && (
              <>
                <h3>Summary table</h3>
                <p className="hint">
                  {campaign.axis_x}
                  {campaign.axis_y ? ` × ${campaign.axis_y}` : ""} · {campaign.status}
                  {["queued", "running"].includes(campaign.status) ? " · auto-refreshing" : ""}
                </p>
                {(() => {
                  const rows = campaignSummaryRows(campaign);
                  const cols = summaryColumns(rows);
                  return (
                    <div className="table-wrap">
                      <table className="table">
                        <thead>
                          <tr>
                            {cols.map((k) => (
                              <th key={k}>{k}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((row, i) => (
                            <tr key={i}>
                              {cols.map((k) => {
                                const v = row[k];
                                if (k === "job_id" && typeof v === "string" && v) {
                                  return (
                                    <td key={k}>
                                      <button
                                        type="button"
                                        className="linkish"
                                        onClick={() => {
                                          const st = String(row.status || "");
                                          void loadJob(v);
                                          setTab(
                                            st === "completed" || st === "failed" ? "results" : "run",
                                          );
                                        }}
                                      >
                                        {v}
                                      </button>
                                    </td>
                                  );
                                }
                                return <td key={k}>{v == null ? "—" : String(v)}</td>;
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  );
                })()}
              </>
            )}
          </section>
        )}

        {tab === "material" && (
          <section className="panel stack">
            <div className="panel-head">
              <h2>Material</h2>
              <div className="chip-row">
                <span className="chip">
                  <span className="chip-k">crystal</span>
                  <span className="chip-v">{material?.crystal || "—"}</span>
                </span>
                <span className="chip">
                  <span className="chip-k">Σ at%</span>
                  <span className={`chip-v ${Math.abs(compositionTotal - 100) > 0.05 ? "tone-fail" : "tone-ok"}`}>
                    {compositionTotal.toFixed(2)}
                  </span>
                </span>
              </div>
            </div>
            <p className="hint">{material?.description}</p>
            {material && crystalInfo && (
              <div className={`alert ${crystalSupported ? "alert-ok" : "alert-warn"}`} role="status">
                {crystalInfo.label}: {crystalInfo.notes}
                {!crystalSupported ? " — dry-run only." : ""}
              </div>
            )}
            {Math.abs(compositionTotal - 100) > 0.05 && compositionTotal > 0 && (
              <div className="alert alert-warn" role="status">
                Composition is {compositionTotal.toFixed(2)} at%. Aegis will proportionally normalize it to 100% before save or run.
              </div>
            )}
            <Field label="Preset" htmlFor="mat-preset">
              <select
                id="mat-preset"
                value={materialId}
                onChange={(e) => {
                  const id = e.target.value;
                  setMaterialId(id);
                  const m = materials.find((x) => x.id === id);
                  if (m) {
                    setComposition(m.composition);
                    setLattice(m.lattice_constant_A);
                    setLatticeC(resolveLatticeC(m, null));
                    const info = crystals.find((c) => c.id === m.crystal.toLowerCase());
                    if (info) {
                      setParam("interstitial_geometry", info.default_interstitial_geometry);
                      setParam("interstitial_direction", info.default_interstitial_direction);
                      setParam("crystal_orient", info.orients[0]?.id || "100");
                    }
                  }
                }}
              >
                {materials.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                    {m.metadata_only ? " (metadata)" : ""} · {m.crystal}
                  </option>
                ))}
              </select>
            </Field>
            <div className="row">
              <h3>Composition</h3>
              <p className="hint">
                Fractions are <strong>substitutional</strong> on lattice sites ({material?.crystal || "bcc"}).
                To place impurities as interstitials, use LAMMPS mode <em>interstitial insert</em>.
              </p>
              <Field label="Units" htmlFor="comp-unit">
                <select
                  id="comp-unit"
                  value={compUnit}
                  onChange={(e) => setCompUnit(e.target.value as "at%" | "wt%")}
                >
                  <option value="at%">Atomic % (at%)</option>
                  <option value="wt%">Weight % (wt%)</option>
                </select>
              </Field>
            </div>
            {compUnit === "wt%" && (
              <p className="hint">Edits in wt% convert to at% using standard atomic masses; recipes always store at%.</p>
            )}
            {composition.map((row, idx) => {
              const wtValues = atToWt(composition);
              return (
              <div className="comp-row" key={idx}>
                <Field label="Element">
                  <input
                    value={row.symbol}
                    onChange={(e) => {
                      const next = [...composition];
                      next[idx] = { ...row, symbol: e.target.value };
                      setComposition(next);
                    }}
                  />
                </Field>
                <Field label={compUnit === "at%" ? "Atomic fraction" : "Weight fraction"} unit={compUnit}>
                  <input
                    type="number"
                    inputMode="decimal"
                    value={compUnit === "at%" ? row.atomic_percent : Number(wtValues[idx].toFixed(4))}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (compUnit === "at%") {
                        const next = [...composition];
                        next[idx] = { ...row, atomic_percent: v };
                        setComposition(next);
                      } else {
                        setComposition(wtEditToAt(composition, idx, v));
                      }
                    }}
                  />
                </Field>
                <button
                  className="secondary"
                  type="button"
                  aria-label={`Remove ${row.symbol}`}
                  onClick={() => setComposition(composition.filter((_, i) => i !== idx))}
                >
                  Remove
                </button>
              </div>
            );})}
            <div className="row">
              <button
                className="secondary"
                type="button"
                onClick={() => setComposition([...composition, { symbol: "Ta", atomic_percent: 0 }])}
              >
                Add element
              </button>
              <Field label="Lattice constant" unit="Å" htmlFor="lattice">
                <input
                  id="lattice"
                  type="number"
                  step="0.001"
                  inputMode="decimal"
                  value={lattice}
                  onChange={(e) => setLattice(Number(e.target.value))}
                />
              </Field>
              {(crystalInfo?.needs_c ||
                (material?.crystal || "").toLowerCase() === "hcp" ||
                (material?.crystal || "").toLowerCase() === "hex") && (
                <Field label="Lattice c" unit="Å" htmlFor="lattice-c">
                  <input
                    id="lattice-c"
                    type="number"
                    step="0.001"
                    inputMode="decimal"
                    value={latticeC ?? effectiveLatticeC ?? ""}
                    onChange={(e) => setLatticeC(e.target.value === "" ? null : Number(e.target.value))}
                  />
                </Field>
              )}
              <div className="row">
                <button
                  type="button"
                  className="secondary"
                  disabled={busy || !material}
                  onClick={async () => {
                    if (!material) return;
                    try {
                      const r = await api<{
                        status: string;
                        lattice_constant_A?: number;
                        lattice_c_A?: number | null;
                        message?: string;
                      }>(`/api/materials/${material.id}/lattice-relax`, { method: "POST" });
                      if (r.status === "ok" && r.lattice_constant_A) {
                        setLattice(r.lattice_constant_A);
                        if (r.lattice_c_A) setLatticeC(r.lattice_c_A);
                      } else {
                        setError(r.message || "ASE relax unavailable — use Export POSCAR for DFT");
                      }
                    } catch (err) {
                      setError(err instanceof Error ? err.message : String(err));
                    }
                  }}
                >
                  Relax lattice (ASE)
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={!material}
                  onClick={() => {
                    const a = document.createElement("a");
                    a.href = `/api/materials/${materialId}/export-poscar`;
                    a.download = `${materialId}.POSCAR`;
                    a.click();
                  }}
                >
                  Export POSCAR
                </button>
              </div>
            </div>
            <button type="button" disabled={busy || compositionTotal <= 0} onClick={saveComposition}>
              Normalize & save override
            </button>
          </section>
        )}

        {tab === "potential" && (
          <div className="stack">
            <section className="panel stack">
              <div className="panel-head">
                <h2>Local potential library</h2>
                <span className="chip">
                  <span className="chip-k">ready</span>
                  <span className="chip-v">{potentials.filter((p) => p.available).length}</span>
                </span>
              </div>
              <p className="hint">
                Select a potential that is on disk (●). Missing curated slots (○) and placeholders (◇) need a NIST
                download or manual upload — Aegis never invents coefficients.
              </p>
              <Field label="Compatible potentials" htmlFor="pot-select">
                <select id="pot-select" value={potentialId} onChange={(e) => setPotentialId(e.target.value)}>
                  {potentials.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.available ? "●" : p.is_placeholder ? "◇" : "○"} {p.name} [{p.source}]
                    </option>
                  ))}
                </select>
              </Field>
              {selectedPot && (
                <div className="stack">
                  <div className="chip-row">
                    <span className="chip">
                      <span className="chip-k">pair_style</span>
                      <span className="chip-v">{selectedPot.lammps_pair_style}</span>
                    </span>
                    <span className="chip">
                      <span className="chip-k">elements</span>
                      <span className="chip-v">{selectedPot.elements.join(" ")}</span>
                    </span>
                    <span className="chip">
                      <span className="chip-k">file</span>
                      <span
                        className={`chip-v ${
                          selectedPot.available
                            ? "tone-ok"
                            : selectedPot.is_placeholder
                              ? "tone-warn"
                              : "tone-fail"
                        }`}
                      >
                        {selectedPot.available
                          ? "on disk"
                          : selectedPot.is_placeholder
                            ? "placeholder"
                            : "missing"}
                      </span>
                    </span>
                  </div>
                  {selectedPot.citation && <p className="hint">{selectedPot.citation}</p>}
                  <div className="row">
                    {selectedPot.source_url && (
                      <a className="linkish" href={selectedPot.source_url} target="_blank" rel="noreferrer">
                        Open source page
                      </a>
                    )}
                    {selectedPot.doi && (
                      <a
                        className="linkish"
                        href={`https://doi.org/${selectedPot.doi}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        DOI {selectedPot.doi}
                      </a>
                    )}
                  </div>
                  {selectedPot.recommended_for?.length > 0 && (
                    <p className="hint">Tags: {selectedPot.recommended_for.join(", ")}</p>
                  )}
                  {selectedPot.warnings?.map((w) => (
                    <div key={w} className="alert alert-warn">
                      {w}
                    </div>
                  ))}
                  {selectedPot.is_placeholder && (
                    <div className="alert alert-warn" role="status">
                      Demo placeholder — jobs use dry-run dumps. Download Zhou04 W from NIST below or upload a published
                      file.
                    </div>
                  )}
                  {!selectedPot.available && !selectedPot.is_placeholder && (
                    <div className="alert alert-fail" role="alert">
                      Unavailable for MD: download from NIST / libraries or upload a file and attach it to this entry.
                    </div>
                  )}
                </div>
              )}
            </section>

            <div className="grid-2">
              <section className="panel stack">
                <h2>NIST / OpenKIM libraries</h2>
                <p className="hint">
                  Curated PFM-relevant downloads from{" "}
                  <a href="https://www.ctcms.nist.gov/potentials/" target="_blank" rel="noreferrer">
                    NIST IPR
                  </a>
                  . Browse-only rows open the repository; downloadable rows fetch the published file into Aegis.
                </p>
                <div className="row">
                  <Field label="Filter" htmlFor="lib-q">
                    <input
                      id="lib-q"
                      value={libQuery}
                      onChange={(e) => setLibQuery(e.target.value)}
                      placeholder="W, Zhou, eam…"
                    />
                  </Field>
                  <Field label="Source" htmlFor="lib-src">
                    <select id="lib-src" value={libSource} onChange={(e) => setLibSource(e.target.value)}>
                      <option value="">all</option>
                      <option value="nist">nist</option>
                      <option value="openkim">openkim</option>
                    </select>
                  </Field>
                </div>
                <div className="stack lib-list">
                  {library.length === 0 && <p className="hint">No library rows for this material/filter.</p>}
                  {library.map((entry) => (
                    <div key={entry.id} className="lib-row">
                      <div>
                        <strong>{entry.name}</strong>
                        <p className="hint">
                          {entry.elements.join("-")}
                          {entry.pair_style ? ` · ${entry.pair_style}` : ""}
                          {entry.installed ? " · installed" : ""}
                        </p>
                      </div>
                      <div className="row">
                        {entry.entry_url && (
                          <a className="linkish" href={entry.entry_url} target="_blank" rel="noreferrer">
                            Open
                          </a>
                        )}
                        {entry.downloadable ? (
                          <button
                            type="button"
                            className="secondary"
                            disabled={busy || entry.installed}
                            onClick={() => void downloadLibraryEntry(entry)}
                          >
                            {entry.installed ? "Installed" : "Download"}
                          </button>
                        ) : (
                          <span className="hint">browse</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                <h3>Import NIST Download URL</h3>
                <Field label="Direct file URL" unit="ctcms.nist.gov/potentials/Download/…" htmlFor="imp-url">
                  <input
                    id="imp-url"
                    value={importUrl}
                    onChange={(e) => setImportUrl(e.target.value)}
                    placeholder="https://www.ctcms.nist.gov/potentials/Download/…"
                  />
                </Field>
                <button type="button" className="secondary" disabled={busy || !importUrl.trim()} onClick={() => void importDownloadUrl()}>
                  Import URL
                </button>
                <h3>Parse NIST entry page</h3>
                <Field label="Entry URL" unit="/potentials/entry/…" htmlFor="entry-url">
                  <input
                    id="entry-url"
                    value={entryUrl}
                    onChange={(e) => setEntryUrl(e.target.value)}
                    placeholder="https://www.ctcms.nist.gov/potentials/entry/…"
                  />
                </Field>
                <button type="button" className="secondary" disabled={busy || !entryUrl.trim()} onClick={() => void scrapeNistEntry()}>
                  List files on entry
                </button>
                {entryFiles.length > 0 && (
                  <div className="stack">
                    {entryFiles.map((f) => (
                      <button
                        key={f.download_url}
                        type="button"
                        className="job-row"
                        disabled={busy}
                        onClick={() => {
                          setImportUrl(f.download_url);
                          void (async () => {
                            setImportUrl(f.download_url);
                            setBusy(true);
                            setError("");
                            try {
                              const pot = await api<Potential>("/api/potentials/library/download", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                  url: f.download_url,
                                  attach_to_id:
                                    selectedPot && (!selectedPot.available || selectedPot.is_placeholder)
                                      ? selectedPot.id
                                      : undefined,
                                  elements: uploadElements.split(/[\s,]+/).filter(Boolean),
                                  lammps_pair_style: uploadPairStyle,
                                  name: f.filename,
                                }),
                              });
                              await refreshPotentials(pot.id);
                            } catch (err) {
                              setError(err instanceof Error ? err.message : String(err));
                            } finally {
                              setBusy(false);
                            }
                          })();
                        }}
                      >
                        <span>{f.filename}</span>
                        <span className="hint">download</span>
                      </button>
                    ))}
                  </div>
                )}
              </section>

              <section className="panel stack">
                <h2>Upload / attach file</h2>
                <p className="hint">
                  Manual fallback when the potential is not in the library index (or for proprietary files you already
                  have).
                </p>
                <Field label="Display name" htmlFor="up-name">
                  <input id="up-name" value={uploadName} onChange={(e) => setUploadName(e.target.value)} />
                </Field>
                <Field label="Elements" unit="space-separated" htmlFor="up-el">
                  <input id="up-el" value={uploadElements} onChange={(e) => setUploadElements(e.target.value)} />
                </Field>
                <Field label="LAMMPS pair_style" htmlFor="up-style">
                  <select
                    id="up-style"
                    value={uploadPairStyle}
                    onChange={(e) => setUploadPairStyle(e.target.value)}
                  >
                    {PAIR_STYLE_WHITELIST.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Potential file" htmlFor="up-file">
                  <input
                    id="up-file"
                    type="file"
                    accept=".eam,.alloy,.fs,.meam,.snap,.table,.dat,.txt"
                    onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                  />
                </Field>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={uploadAttachTo}
                    onChange={(e) => setUploadAttachTo(e.target.checked)}
                  />
                  Attach to selected catalog entry when it is missing/placeholder
                </label>
                <button type="button" disabled={busy || !uploadFile} onClick={() => void uploadPotential()}>
                  {uploadAttachTo && selectedPot && (!selectedPot.available || selectedPot.is_placeholder)
                    ? `Attach to ${selectedPot.id}`
                    : "Upload as new potential"}
                </button>
              </section>
            </div>
          </div>
        )}

        {tab === "scenario" && (
          <section className="panel stack">
            <h2>Irradiation scenario</h2>
            <p className="hint">
              Fuel choices set default PKA/He energies and temperature. They are not a tokamak transport model.
            </p>
            <div className="row">
              <Field label="Fuel preset" htmlFor="scenario">
                <select id="scenario" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
                  {scenarios.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label} ({s.fuel})
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Project name" htmlFor="proj">
                <input id="proj" value={projectName} onChange={(e) => setProjectName(e.target.value)} />
              </Field>
            </div>
            <p className="hint">{scenario?.description}</p>
            {scenario && (
              <div className="chip-row">
                {Object.entries(scenario.defaults)
                  .slice(0, 8)
                  .map(([k, v]) => (
                    <span className="chip" key={k}>
                      <span className="chip-k">{k}</span>
                      <span className="chip-v">{String(v)}</span>
                    </span>
                  ))}
              </div>
            )}
          </section>
        )}

        {tab === "params" && (
          <section className="panel stack">
            <div className="panel-head">
              <h2>LAMMPS parameters</h2>
              <span className="chip">
                <span className="chip-k">atoms proxy</span>
                <span className="chip-v">
                  ~{cellVolume * atomsPerCell} {crystalInfo?.label || "lattice"} sites
                </span>
              </span>
            </div>
            <fieldset className="fieldset">
              <legend>Mode & thermostat</legend>
              <div className="row">
                <Field label="Mode" htmlFor="mode">
                  <select
                    id="mode"
                    value={params.mode}
                    onChange={(e) => {
                      const next = e.target.value;
                      modeDirty.current = true;
                      setParams((p) => {
                        const patch: Partial<RunParams> = { mode: next };
                        if (next === "surface") {
                          patch.boundary = "p p s";
                        } else if (p.mode === "surface" && (p.boundary || "").trim() === "p p s") {
                          patch.boundary = "p p p";
                        }
                        return { ...p, ...patch };
                      });
                    }}
                  >
                    <option value="cascade">cascade / PKA</option>
                    <option value="implant">ion implant (bulk)</option>
                    <option value="surface">low-E surface (fuzz proxy)</option>
                    <option value="interstitial">interstitial insert (lattice dirs)</option>
                  </select>
                </Field>
                <Field label="Temperature" unit="K" htmlFor="T">
                  <input
                    id="T"
                    type="number"
                    inputMode="decimal"
                    value={params.temperature_K}
                    onChange={(e) => setParam("temperature_K", Number(e.target.value))}
                  />
                </Field>
                <Field label="Ensemble" htmlFor="ensemble">
                  <select
                    id="ensemble"
                    value={params.ensemble}
                    onChange={(e) => setParam("ensemble", e.target.value)}
                  >
                    <option value="nve">NVE</option>
                    <option value="nvt">NVT</option>
                  </select>
                </Field>
                <Field label="Thermostat damping" unit="ps" htmlFor="damp">
                  <input
                    id="damp"
                    type="number"
                    step="0.01"
                    value={params.damp_ps}
                    onChange={(e) => setParam("damp_ps", Number(e.target.value))}
                  />
                </Field>
                <Field label="Seed" htmlFor="seed">
                  <input
                    id="seed"
                    type="number"
                    inputMode="numeric"
                    value={params.seed}
                    onChange={(e) => setParam("seed", Number(e.target.value))}
                  />
                </Field>
              </div>
            </fieldset>
            <fieldset className="fieldset">
              <legend>System</legend>
              <div className="row">
                {(["nx", "ny", "nz"] as const).map((k) => (
                  <Field key={k} label={k} unit="unit cells" htmlFor={k}>
                    <input
                      id={k}
                      type="number"
                      inputMode="numeric"
                      value={params[k]}
                      onChange={(e) => setParam(k, Number(e.target.value))}
                    />
                  </Field>
                ))}
                <Field label="Boundary" htmlFor="boundary">
                  <input
                    id="boundary"
                    value={params.boundary}
                    onChange={(e) => setParam("boundary", e.target.value)}
                  />
                </Field>
                <Field label="Crystal orientation" unit="x-axis" htmlFor="orient">
                  <select
                    id="orient"
                    value={
                      (crystalInfo?.orients || [{ id: "100" }, { id: "110" }, { id: "111" }]).some(
                        (o) => o.id === params.crystal_orient,
                      )
                        ? params.crystal_orient
                        : (crystalInfo?.orients?.[0]?.id || "100")
                    }
                    onChange={(e) => setParam("crystal_orient", e.target.value)}
                  >
                    {(crystalInfo?.orients || [
                      { id: "100", label: "⟨100⟩" },
                      { id: "110", label: "⟨110⟩" },
                      { id: "111", label: "⟨111⟩" },
                    ]).map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <div className="row">
                <Field label="Structure" htmlFor="struct-kind">
                  <select
                    id="struct-kind"
                    value={params.structure_kind}
                    onChange={(e) => setParam("structure_kind", e.target.value)}
                  >
                    <option value="single_crystal">single crystal</option>
                    <option value="polycrystal">polycrystal (Voronoi seeds)</option>
                  </select>
                </Field>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={params.run_dxa}
                    onChange={(e) => setParam("run_dxa", e.target.checked)}
                  />
                  Run OVITO DXA after job (if installed)
                </label>
              </div>
              {params.structure_kind === "polycrystal" && (
                <div className="row">
                  <Field label="Grains" htmlFor="poly-n">
                    <input
                      id="poly-n"
                      type="number"
                      min={2}
                      max={64}
                      value={params.poly_n_grains}
                      onChange={(e) => setParam("poly_n_grains", Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Texture" htmlFor="poly-tex">
                    <select
                      id="poly-tex"
                      value={params.poly_texture}
                      onChange={(e) => setParam("poly_texture", e.target.value)}
                    >
                      <option value="random">random</option>
                      <option value="fiber">fiber (z)</option>
                    </select>
                  </Field>
                  <Field label="Poly seed" htmlFor="poly-seed">
                    <input
                      id="poly-seed"
                      type="number"
                      value={params.poly_seed}
                      onChange={(e) => setParam("poly_seed", Number(e.target.value))}
                    />
                  </Field>
                </div>
              )}
            </fieldset>
            <fieldset className="fieldset">
              <legend>Cascade / PKA</legend>
              <p className="hint">
                Pick PKA energy, direction, and lattice site. With auto stages on, Aegis densifies dumps through
                growth → peak → quench → residual so OVITO can scrub each regime (see{" "}
                <code>cascade_stages_OVITO.txt</code> in the job folder).
              </p>
              <div className="row">
                <Field label="PKA species" htmlFor="pka-sp">
                  <input
                    id="pka-sp"
                    value={params.pka_species}
                    onChange={(e) => setParam("pka_species", e.target.value)}
                  />
                </Field>
                <Field label="Energy" unit="eV" htmlFor="pka-e">
                  <>
                    <input
                      id="pka-e"
                      type="number"
                      inputMode="decimal"
                      value={params.pka_energy_eV}
                      onChange={(e) => setParam("pka_energy_eV", Number(e.target.value))}
                    />
                    <span className="field-helper">{(params.pka_energy_eV / 1000).toLocaleString()} keV</span>
                  </>
                </Field>
                <Field label="Direction" unit="random | h k l" htmlFor="pka-d">
                  <input
                    id="pka-d"
                    value={params.pka_direction}
                    onChange={(e) => setParam("pka_direction", e.target.value)}
                  />
                </Field>
                <Field label="# PKAs" htmlFor="n-pka">
                  <input
                    id="n-pka"
                    type="number"
                    inputMode="numeric"
                    value={params.n_pkas}
                    onChange={(e) => setParam("n_pkas", Number(e.target.value))}
                  />
                </Field>
                <Field label="PKA delay" unit="steps" htmlFor="pka-delay">
                  <input
                    id="pka-delay"
                    type="number"
                    value={params.pka_delay_steps}
                    onChange={(e) => setParam("pka_delay_steps", Number(e.target.value))}
                  />
                </Field>
              </div>
              <div className="row">
                <Field label="PKA site" htmlFor="pka-site">
                  <select
                    id="pka-site"
                    value={params.pka_site}
                    onChange={(e) => setParam("pka_site", e.target.value)}
                  >
                    <option value="center">box center (snapped to lattice)</option>
                    <option value="coords">fractional coords (snapped)</option>
                    <option value="random">random lattice site</option>
                  </select>
                </Field>
                {params.pka_site === "coords" && (
                  <>
                    <Field label="x frac" unit="0–1" htmlFor="pka-fx">
                      <input
                        id="pka-fx"
                        type="number"
                        step="0.01"
                        min={0}
                        max={1}
                        value={params.pka_frac_x}
                        onChange={(e) => setParam("pka_frac_x", Number(e.target.value))}
                      />
                    </Field>
                    <Field label="y frac" unit="0–1" htmlFor="pka-fy">
                      <input
                        id="pka-fy"
                        type="number"
                        step="0.01"
                        min={0}
                        max={1}
                        value={params.pka_frac_y}
                        onChange={(e) => setParam("pka_frac_y", Number(e.target.value))}
                      />
                    </Field>
                    <Field label="z frac" unit="0–1" htmlFor="pka-fz">
                      <input
                        id="pka-fz"
                        type="number"
                        step="0.01"
                        min={0}
                        max={1}
                        value={params.pka_frac_z}
                        onChange={(e) => setParam("pka_frac_z", Number(e.target.value))}
                      />
                    </Field>
                  </>
                )}
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={params.cascade_auto_stages}
                    onChange={(e) => setParam("cascade_auto_stages", e.target.checked)}
                  />
                  Auto stage dumps (growth / peak / quench / residual)
                </label>
              </div>
            </fieldset>
            <fieldset className="fieldset">
              <legend>Implant</legend>
              <div className="row">
                <Field label="Ion" htmlFor="ion">
                  <input id="ion" value={params.ion_type} onChange={(e) => setParam("ion_type", e.target.value)} />
                </Field>
                <Field label="Ion energy" unit="eV" htmlFor="ion-e">
                  <input
                    id="ion-e"
                    type="number"
                    inputMode="decimal"
                    value={params.ion_energy_eV}
                    onChange={(e) => setParam("ion_energy_eV", Number(e.target.value))}
                  />
                </Field>
                <Field label="Ion count" htmlFor="ion-n">
                  <input
                    id="ion-n"
                    type="number"
                    inputMode="numeric"
                    value={params.ion_count}
                    onChange={(e) => setParam("ion_count", Number(e.target.value))}
                  />
                </Field>
                <Field label="Incidence angle" unit="deg" htmlFor="ion-angle">
                  <input
                    id="ion-angle"
                    type="number"
                    step="0.1"
                    value={params.ion_angle_deg}
                    onChange={(e) => setParam("ion_angle_deg", Number(e.target.value))}
                  />
                </Field>
              </div>
            </fieldset>
            {params.mode === "surface" && (
              <fieldset className="fieldset">
                <legend>Surface MD (Phase-3)</legend>
                <p className="hint">
                  Free-surface slab with vacuum; low-E He/D fluence is a discrete ion-count proxy — not a plasma sheath.
                </p>
                <div className="row">
                  <Field label="Vacuum layers" unit="lattice" htmlFor="vac-layers">
                    <input
                      id="vac-layers"
                      type="number"
                      value={params.vacuum_layers}
                      onChange={(e) => setParam("vacuum_layers", Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Surface fluence" unit="ions" htmlFor="surf-flu">
                    <input
                      id="surf-flu"
                      type="number"
                      value={params.surface_fluence_ions}
                      onChange={(e) => setParam("surface_fluence_ions", Number(e.target.value))}
                    />
                  </Field>
                </div>
              </fieldset>
            )}
            {params.mode === "interstitial" && (
              <fieldset className="fieldset">
                <legend>Interstitial insertion</legend>
                <p className="hint">
                  Material composition stays substitutional on {material?.crystal || "host"} sites. This mode adds
                  extra interstitial atoms (or SIA pairs) along crystal-aware directions — not random alloy swaps.
                </p>
                <div className="row">
                  <Field label="Species" htmlFor="int-sp">
                    <input
                      id="int-sp"
                      value={params.interstitial_species}
                      onChange={(e) => setParam("interstitial_species", e.target.value)}
                    />
                  </Field>
                  <Field label="Count" unit="sites / dumbbells" htmlFor="int-n">
                    <input
                      id="int-n"
                      type="number"
                      min={1}
                      max={64}
                      value={params.interstitial_count}
                      onChange={(e) => setParam("interstitial_count", Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Lattice direction" htmlFor="int-dir">
                    <select
                      id="int-dir"
                      value={
                        intDirectionOptions.includes(params.interstitial_direction)
                          ? params.interstitial_direction
                          : "custom"
                      }
                      onChange={(e) => {
                        if (e.target.value === "custom") {
                          setParam("interstitial_direction", "1 0 0");
                        } else {
                          setParam("interstitial_direction", e.target.value);
                        }
                      }}
                    >
                      {intDirectionOptions.map((d) => (
                        <option key={d} value={d}>
                          {d === "100" || d === "110" || d === "111" ? `\u27E8${d}\u27E9` : d}
                        </option>
                      ))}
                      <option value="custom">custom Miller…</option>
                    </select>
                  </Field>
                  {!intDirectionOptions.includes(params.interstitial_direction) && (
                    <Field label="Miller indices" unit="h k l" htmlFor="int-miller">
                      <input
                        id="int-miller"
                        value={params.interstitial_direction}
                        onChange={(e) => setParam("interstitial_direction", e.target.value)}
                      />
                    </Field>
                  )}
                </div>
                <div className="row">
                  <Field label="Geometry" htmlFor="int-geom">
                    <select
                      id="int-geom"
                      value={
                        (crystalInfo?.interstitial_geometries || []).includes(params.interstitial_geometry)
                          ? params.interstitial_geometry
                          : crystalInfo?.default_interstitial_geometry || params.interstitial_geometry
                      }
                      onChange={(e) => setParam("interstitial_geometry", e.target.value)}
                    >
                      {(crystalInfo?.interstitial_geometries || ["octahedral", "tetrahedral", "dumbbell", "crowdion"]).map(
                        (g) => (
                          <option key={g} value={g}>
                            {g}
                          </option>
                        ),
                      )}
                    </select>
                  </Field>
                  <Field label="Pair offset" unit="Å · blank = 0.25 a" htmlFor="int-off">
                    <input
                      id="int-off"
                      type="number"
                      step="0.01"
                      value={params.interstitial_offset_A ?? ""}
                      onChange={(e) =>
                        setParam(
                          "interstitial_offset_A",
                          e.target.value === "" ? null : Number(e.target.value),
                        )
                      }
                    />
                  </Field>
                  <Field label="Kick energy" unit="eV · 0 = static insert" htmlFor="int-e">
                    <input
                      id="int-e"
                      type="number"
                      step="0.1"
                      value={params.interstitial_energy_eV}
                      onChange={(e) => setParam("interstitial_energy_eV", Number(e.target.value))}
                    />
                  </Field>
                </div>
              </fieldset>
            )}
            <details className="advanced">
              <summary>Advanced dynamics & output</summary>
              <div className="row" style={{ marginTop: "0.75rem" }}>
                <Field label="Timestep" unit="fs" htmlFor="dt">
                  <input
                    id="dt"
                    type="number"
                    step="0.0001"
                    value={params.timestep_fs}
                    onChange={(e) => setParam("timestep_fs", Number(e.target.value))}
                  />
                </Field>
                <Field label="Max steps" htmlFor="steps">
                  <input
                    id="steps"
                    type="number"
                    value={params.max_steps}
                    onChange={(e) => setParam("max_steps", Number(e.target.value))}
                  />
                </Field>
                <Field label="Thermo every" htmlFor="thermo">
                  <input
                    id="thermo"
                    type="number"
                    value={params.thermo_every}
                    onChange={(e) => setParam("thermo_every", Number(e.target.value))}
                  />
                </Field>
                <Field label="Dump every" htmlFor="dump">
                  <input
                    id="dump"
                    type="number"
                    value={params.dump_every}
                    onChange={(e) => setParam("dump_every", Number(e.target.value))}
                  />
                </Field>
                <Field label="Neighbor skin" unit="Å" htmlFor="skin">
                  <input
                    id="skin"
                    type="number"
                    step="0.1"
                    value={params.neighbor_skin}
                    onChange={(e) => setParam("neighbor_skin", Number(e.target.value))}
                  />
                </Field>
                <Field label="Dump style" htmlFor="dump-style">
                  <select id="dump-style" value="custom" onChange={() => setParam("dump_style", "custom")}>
                    <option value="custom">custom (id type x y z)</option>
                  </select>
                </Field>
                <Field label="Restart every" unit="steps · 0 disables" htmlFor="restart">
                  <input
                    id="restart"
                    type="number"
                    value={params.restart_every}
                    onChange={(e) => setParam("restart_every", Number(e.target.value))}
                  />
                </Field>
                <Field label="Wigner–Seitz lattice" unit="Å · blank = material" htmlFor="ws-lattice">
                  <input
                    id="ws-lattice"
                    type="number"
                    step="0.001"
                    value={params.ws_lattice_A ?? ""}
                    onChange={(e) =>
                      setParam("ws_lattice_A", e.target.value === "" ? null : Number(e.target.value))
                    }
                  />
                </Field>
                <Field label="Cluster cutoff" unit="Å" htmlFor="cut">
                  <input
                    id="cut"
                    type="number"
                    step="0.1"
                    value={params.cluster_cutoff_A}
                    onChange={(e) => setParam("cluster_cutoff_A", Number(e.target.value))}
                  />
                </Field>
              </div>
            </details>
            <label className="check-row">
              <input
                type="checkbox"
                checked={params.confirm_large}
                onChange={(e) => setParam("confirm_large", e.target.checked)}
              />
              Confirm large cell (&gt;20³ unit cells)
            </label>
            <label className="check-row">
              <input type="checkbox" checked={runKart} onChange={(e) => setRunKart(e.target.checked)} />
              Queue KART anneal after MD
              {!engines?.kart_found && <span className="unit"> · will stub if binary missing</span>}
            </label>
            <label className="check-row">
              <input type="checkbox" checked={runMmonca} onChange={(e) => setRunMmonca(e.target.checked)} />
              Queue MMonCa OKMC (optional comparison)
              {!engines?.mmonca_found && <span className="unit"> · stubs if binary missing</span>}
            </label>
            {runKart && (
              <fieldset className="fieldset">
                <legend>k-ART anneal (Phase-2)</legend>
                <div className="row">
                  <Field label="Anneal temperature" unit="K" htmlFor="kart-temperature">
                    <input
                      id="kart-temperature"
                      type="number"
                      value={kartTemperatureK}
                      onChange={(e) => setKartTemperatureK(Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Maximum events" htmlFor="kart-events">
                    <input
                      id="kart-events"
                      type="number"
                      value={kartMaxEvents}
                      onChange={(e) => setKartMaxEvents(Number(e.target.value))}
                    />
                  </Field>
                </div>
                <div className="row">
                  <Field label="Wall-clock limit" unit="s" htmlFor="kart-wall">
                    <input
                      id="kart-wall"
                      type="number"
                      value={kartMaxWallS}
                      onChange={(e) => setKartMaxWallS(Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Max KMC time" unit="s" htmlFor="kart-kmc-t">
                    <input
                      id="kart-kmc-t"
                      type="number"
                      step="0.001"
                      value={kartMaxKmcTimeS}
                      onChange={(e) => setKartMaxKmcTimeS(Number(e.target.value))}
                    />
                  </Field>
                </div>
                <Field label="DOE temperatures" unit="optional, comma-separated K" htmlFor="kart-doe">
                  <input
                    id="kart-doe"
                    placeholder="e.g. 400, 600, 800"
                    value={kartDoeTemps}
                    onChange={(e) => setKartDoeTemps(e.target.value)}
                  />
                </Field>
                <p className="hint">
                  DOE runs multiple anneals on the same cascade. Aegis writes a kart_work/T* handoff package per
                  temperature (initial.conf, conf.lammps, KMC.sh.aegis).
                </p>
              </fieldset>
            )}
            <button type="button" disabled={busy || blockers.length > 0} onClick={runJob}>
              Run job
            </button>
          </section>
        )}

        {tab === "run" && (
          <section className="panel stack">
            <div className="panel-head">
              <h2>Run console</h2>
              <Field label="Job history" htmlFor="job-history">
                <select
                  id="job-history"
                  value={job?.id || ""}
                  onChange={(e) => void loadJob(e.target.value)}
                >
                  <option value="">Select past job…</option>
                  {jobs.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.project_name} · {item.status} · {item.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            {job ? (
              <>
                <div className="chip-row">
                  <span className="chip">
                    <span className="chip-k">id</span>
                    <span className="chip-v">{job.id}</span>
                  </span>
                  <span className="chip">
                    <span className="chip-k">status</span>
                    <span className="chip-v">{job.status}</span>
                  </span>
                  <span className="chip">
                    <span className="chip-k">msg</span>
                    <span className="chip-v">{job.message}</span>
                  </span>
                </div>
                <div className="log" aria-live="polite">
                  {log || "Waiting for log…"}
                </div>
                <div className="row">
                  <Field label="HPC scheduler" htmlFor="hpc-sched-run">
                    <select id="hpc-sched-run" value={hpcScheduler} onChange={(e) => setHpcScheduler(e.target.value)}>
                      <option value="slurm">Slurm</option>
                      <option value="pbs">PBS</option>
                      <option value="none">files only</option>
                    </select>
                  </Field>
                  <Field label="Cores" htmlFor="hpc-cores-run">
                    <input
                      id="hpc-cores-run"
                      type="number"
                      value={hpcCores}
                      onChange={(e) => setHpcCores(Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Walltime" unit="HH:MM:SS" htmlFor="hpc-wall-run">
                    <input id="hpc-wall-run" value={hpcWalltime} onChange={(e) => setHpcWalltime(e.target.value)} />
                  </Field>
                  <button type="button" className="secondary" disabled={busy} onClick={() => void exportHpc("job")}>
                    Export HPC pack
                  </button>
                  <button
                    className="secondary"
                    type="button"
                    disabled={busy || ["completed", "failed", "cancelled"].includes(job.status)}
                    onClick={() => void cancelJob()}
                  >
                    Cancel job
                  </button>
                </div>
              </>
            ) : (
              <div className="empty">
                <div className="empty-kicker">No active job</div>
                <h3>Queue a cascade or implant</h3>
                <p className="hint">Configure material → potential → scenario → LAMMPS, then Run.</p>
                <ol>
                  <li>Pick a potential with a file on disk</li>
                  <li>Review cell size and PKA/He energy</li>
                  <li>Use the top-bar Run job control</li>
                </ol>
              </div>
            )}
          </section>
        )}

        {tab === "results" && (
          <div className="stack">
            <section className="panel">
              <StructureViewer jobId={job?.id || null} refreshKey={job?.status} />
            </section>
            {cascadeTimeline?.stages && cascadeTimeline.stages.length > 0 && (
              <section className="panel stack">
                <h2>Cascade stages</h2>
                <p className="hint">{cascadeTimeline.note}</p>
                {cascadeTimeline.extended_max_steps && (
                  <div className="alert alert-warn">
                    Auto stages extended the cascade past your max_steps so quench/residual could finish (
                    {cascadeTimeline.total_steps} steps total).
                  </div>
                )}
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>stage</th>
                        <th>label</th>
                        <th>timesteps</th>
                        <th>dump every</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cascadeTimeline.stages.map((st) => (
                        <tr key={st.id}>
                          <td>{st.id}</td>
                          <td>{st.label}</td>
                          <td>
                            {st.timestep_start ?? 0}–{st.timestep_end ?? st.steps}
                          </td>
                          <td>{st.dump_every}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="hint">
                  OVITO: load <code>dump.initial.lammpstrj</code>, then <code>dump.cascade.*.lammpstrj</code>; stage
                  bookmarks are <code>dump.stage.*.lammpstrj</code>. Use <strong>Download cascade GIF</strong> for a
                  quick 2D preview of the dump series (also written as <code>animation.gif</code> in the job folder).
                </p>
              </section>
            )}
          <div className="grid-2">
            <section className="panel stack">
              <div className="panel-head">
                <h2>Defect summary</h2>
                <div className="row">
                  <button type="button" className="secondary" disabled={!defects} onClick={exportDefects}>
                    Export defects JSON
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={!job || job.status !== "completed"}
                    onClick={() => {
                      if (!job) return;
                      const a = document.createElement("a");
                      a.href = `/api/jobs/${job.id}/animation.gif`;
                      a.download = `aegis-${job.id}.gif`;
                      a.click();
                    }}
                  >
                    Download cascade GIF
                  </button>
                </div>
              </div>
              <div className="alert alert-warn">
                SIA/vacancy counts use a Wigner–Seitz proxy. Validate production conclusions against the trajectory,
                reference lattice, and a domain-standard analysis workflow.
              </div>
              {defects?.summary ? (
                <table className="table">
                  <tbody>
                    {Object.entries(defects.summary).map(([k, v]) => (
                      <tr key={k}>
                        <th>{k}</th>
                        <td>{typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="empty">
                  <div className="empty-kicker">Awaiting analysis</div>
                  <h3>No defect products yet</h3>
                  <p className="hint">Complete a run to populate Wigner–Seitz proxy metrics.</p>
                </div>
              )}
              {job?.surface_summary && (
                <>
                  <h3>Surface / fuzz proxies</h3>
                  <p className="hint">Phase-3 engineering metrics — not calibrated sputtering yields.</p>
                  <div className="chip-row">
                    {Object.entries(job.surface_summary).map(([k, v]) => (
                      <span className="chip" key={k}>
                        <span className="chip-k">{k.replace(/_/g, " ")}</span>
                        <span className="chip-v">{String(v)}</span>
                      </span>
                    ))}
                  </div>
                </>
              )}
              <h3>Cluster sizes</h3>
              <div className="chart" aria-hidden={clusterSizes.length === 0}>
                {clusterSizes.length === 0 && <span className="hint">—</span>}
                {clusterSizes.map((s, i) => (
                  <div
                    key={i}
                    className="bar"
                    style={{ height: `${(s / maxCluster) * 100}%` }}
                    title={`size ${s}`}
                  />
                ))}
              </div>
              {(kartSummary || job?.kart_summary) && (
                <>
                  <h3>KART anneal</h3>
                  {(() => {
                    const ks = kartSummary || (job?.kart_summary as KartSummary);
                    const runs = ks?.runs?.length ? ks.runs : null;
                    return (
                      <div className="stack">
                        <div className="chip-row">
                          <span className="chip">
                            <span className="chip-k">status</span>
                            <span className="chip-v">{ks?.status || "—"}</span>
                          </span>
                          {ks?.doe && (
                            <span className="chip">
                              <span className="chip-k">DOE</span>
                              <span className="chip-v">{ks.temperatures_K?.join(", ")} K</span>
                            </span>
                          )}
                          {ks?.handoff && (
                            <span className="chip">
                              <span className="chip-k">handoff</span>
                              <span className="chip-v">{ks.handoff}</span>
                            </span>
                          )}
                        </div>
                        <p className="hint">{ks?.message}</p>
                        {runs ? (
                          runs.map((r) => (
                            <div key={r.temperature_K} className="stack">
                              <h4>
                                T = {r.temperature_K} K · {r.status}
                              </h4>
                              <KartTimeline
                                events={r.events || []}
                                label={`Barrier timeline (${r.events?.[0]?.source || "events"})`}
                              />
                            </div>
                          ))
                        ) : (
                          <KartTimeline
                            events={(ks?.events as KartEvent[]) || []}
                            label="Barrier timeline"
                          />
                        )}
                        {job?.status === "completed" && (
                          <button
                            type="button"
                            className="secondary"
                            disabled={busy}
                            onClick={() => void reannealDoe()}
                          >
                            Re-anneal DOE on this cascade
                          </button>
                        )}
                      </div>
                    );
                  })()}
                </>
              )}
              {job?.mmonca_summary && (
                <>
                  <h3>MMonCa OKMC</h3>
                  <div className="chip-row">
                    <span className="chip">
                      <span className="chip-k">status</span>
                      <span className="chip-v">{String((job.mmonca_summary as { status?: string }).status || "—")}</span>
                    </span>
                  </div>
                  <p className="hint">{String((job.mmonca_summary as { message?: string }).message || "")}</p>
                  <pre className="log" style={{ height: "auto", maxHeight: 160 }}>
                    {JSON.stringify((job.mmonca_summary as { final_objects?: unknown }).final_objects || job.mmonca_summary, null, 2)}
                  </pre>
                </>
              )}
            </section>
            <section className="panel stack">
              <h2>Defect markers</h2>
              <DefectViz points={defects?.points || []} />
              <p className="hint">Vacancy = red · interstitial = copper · other = green. WS proxy markers (not full atoms).</p>
            </section>
          </div>
            <section className="panel stack">
              <div className="panel-head">
                <h2>OVITO DXA</h2>
                <div className="chip-row">
                  <button
                    type="button"
                    className="secondary"
                    disabled={!job || busy}
                    onClick={async () => {
                      if (!job) return;
                      setBusy(true);
                      try {
                        setDxaSummary(await api(`/api/jobs/${job.id}/dxa?refresh=true`));
                        setEngines(await api<EngineStatus>("/api/engines/status"));
                      } catch (err) {
                        setError(err instanceof Error ? err.message : String(err));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Run / refresh DXA
                  </button>
                  {job && dxaSummary && (dxaSummary as { ca_file?: string }).ca_file ? (
                    <a className="secondary btn-link" href={`/api/jobs/${job.id}/dxa/ca`}>
                      Download .ca
                    </a>
                  ) : null}
                </div>
              </div>
              <p className="hint">
                {engines?.ovito_message ||
                  "Install with pip install -U ovito (or set AEGIS_OVITO_BIN). Aegis never fabricates dislocation networks."}
              </p>
              {dxaSummary ? (
                <>
                  <div className="chip-row">
                    <span className="chip">
                      <span className="chip-k">status</span>
                      <span className="chip-v">{String((dxaSummary as { status?: string }).status || "—")}</span>
                    </span>
                    {(dxaSummary as { ovito_lattice?: string }).ovito_lattice ? (
                      <span className="chip">
                        <span className="chip-k">lattice</span>
                        <span className="chip-v">
                          {String((dxaSummary as { crystal?: string }).crystal || "")} →{" "}
                          {String((dxaSummary as { ovito_lattice?: string }).ovito_lattice)}
                        </span>
                      </span>
                    ) : null}
                    {(dxaSummary as { dislocation_length_A?: number | null }).dislocation_length_A !=
                    null ? (
                      <span className="chip">
                        <span className="chip-k">Σ L</span>
                        <span className="chip-v">
                          {Number(
                            (dxaSummary as { dislocation_length_A?: number }).dislocation_length_A,
                          ).toFixed(2)}{" "}
                          Å
                        </span>
                      </span>
                    ) : null}
                    {(dxaSummary as { n_dislocation_segments?: number | null }).n_dislocation_segments !=
                    null ? (
                      <span className="chip">
                        <span className="chip-k">segments</span>
                        <span className="chip-v">
                          {String(
                            (dxaSummary as { n_dislocation_segments?: number }).n_dislocation_segments,
                          )}
                        </span>
                      </span>
                    ) : null}
                    {(dxaSummary as { how?: string }).how ? (
                      <span className="chip">
                        <span className="chip-k">via</span>
                        <span className="chip-v">{String((dxaSummary as { how?: string }).how)}</span>
                      </span>
                    ) : null}
                  </div>
                  {(dxaSummary as { message?: string }).message ? (
                    <p className="hint">{String((dxaSummary as { message?: string }).message)}</p>
                  ) : null}
                  {(dxaSummary as { ca_hint?: string }).ca_hint ? (
                    <p className="hint">{String((dxaSummary as { ca_hint?: string }).ca_hint)}</p>
                  ) : null}
                  {(dxaSummary as { install_hint?: string }).install_hint ? (
                    <pre className="log" style={{ height: "auto", maxHeight: 80 }}>
                      {(dxaSummary as { install_hint?: string }).install_hint}
                    </pre>
                  ) : null}
                  <details>
                    <summary className="hint">Raw DXA JSON</summary>
                    <pre className="log" style={{ height: "auto", maxHeight: 220 }}>
                      {JSON.stringify(dxaSummary, null, 2)}
                    </pre>
                  </details>
                </>
              ) : (
                <p className="hint">No DXA summary yet — enable “Run OVITO DXA after job” or click Run / refresh.</p>
              )}
            </section>
          </div>
        )}

        {tab === "engines" && (
          <section className="panel stack">
            <h2>Engines</h2>
            <div className="grid-2">
              <div className="stack">
                <h3>LAMMPS</h3>
                <div className="chip-row">
                  <span className="chip">
                    <span className="chip-k">status</span>
                    <span className={`chip-v ${engines?.lammps_found ? "tone-ok" : "tone-warn"}`}>
                      {engines?.lammps_found ? "found" : "missing"}
                    </span>
                  </span>
                </div>
                <p className="hint">{engines?.lammps_path || "Set AEGIS_LAMMPS_BIN or run setup_and_run.cmd"}</p>
                <p className="hint">{engines?.lammps_version}</p>
              </div>
              <div className="stack">
                <h3>KART (k-ART)</h3>
                <div className="chip-row">
                  <span className="chip">
                    <span className="chip-k">status</span>
                    <span className={`chip-v ${engines?.kart_found ? "tone-ok" : "tone-warn"}`}>
                      {engines?.kart_found ? "found" : "not built"}
                    </span>
                  </span>
                  <span className="chip">
                    <span className="chip-k">pin</span>
                    <span className="chip-v">{engines?.kart_commit_expected}</span>
                  </span>
                </div>
                <p className="hint">{engines?.kart_root || "third_party/kart not present"}</p>
                <p className="hint">{engines?.kart_message}</p>
              </div>
              <div className="stack">
                <h3>MMonCa (optional OKMC)</h3>
                <div className="chip-row">
                  <span className="chip">
                    <span className="chip-k">status</span>
                    <span className={`chip-v ${engines?.mmonca_found ? "tone-ok" : "tone-warn"}`}>
                      {engines?.mmonca_found ? "found" : "optional"}
                    </span>
                  </span>
                </div>
                <p className="hint">{engines?.mmonca_path || "Not required — KART is the primary KMC path"}</p>
                <p className="hint">{engines?.mmonca_message}</p>
              </div>
              <div className="stack">
                <h3>ASE / DFT relax</h3>
                <div className="chip-row">
                  <span className="chip">
                    <span className="chip-k">ASE</span>
                    <span className={`chip-v ${engines?.ase_found ? "tone-ok" : "tone-warn"}`}>
                      {engines?.ase_found ? "found" : "missing"}
                    </span>
                  </span>
                </div>
                <p className="hint">{engines?.ase_message}</p>
              </div>
              <div className="stack">
                <h3>OVITO DXA</h3>
                <div className="chip-row">
                  <span className="chip">
                    <span className="chip-k">OVITO</span>
                    <span className={`chip-v ${engines?.ovito_found ? "tone-ok" : "tone-warn"}`}>
                      {engines?.ovito_found ? "found" : "missing"}
                    </span>
                  </span>
                  {engines?.ovito_mode ? (
                    <span className="chip">
                      <span className="chip-k">mode</span>
                      <span className="chip-v">{engines.ovito_mode}</span>
                    </span>
                  ) : null}
                  {engines?.ovito_version ? (
                    <span className="chip">
                      <span className="chip-k">ver</span>
                      <span className="chip-v">{engines.ovito_version}</span>
                    </span>
                  ) : null}
                </div>
                <p className="hint">{engines?.ovito_message}</p>
                <p className="hint">{engines?.ovito_path || "Optional: set AEGIS_OVITO_BIN to ovitos.exe"}</p>
                <div className="chip-row">
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy || Boolean(engines?.ovito_found && engines?.ovito_mode?.includes("module"))}
                    onClick={async () => {
                      setBusy(true);
                      setError("");
                      try {
                        const r = await api<{
                          ok: boolean;
                          message?: string;
                          install?: { pip_command?: string };
                        }>("/api/engines/ovito/install", { method: "POST" });
                        setEngines(await api<EngineStatus>("/api/engines/status"));
                        if (!r.ok) {
                          setError(
                            r.message ||
                              r.install?.pip_command ||
                              "OVITO pip install failed — see Engines hint",
                          );
                        }
                      } catch (err) {
                        setError(err instanceof Error ? err.message : String(err));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Install OVITO (pip)
                  </button>
                  <a
                    className="secondary btn-link"
                    href="https://docs.ovito.org/python/introduction/installation.html"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Docs
                  </a>
                </div>
              </div>
              <div className="stack">
                <h3>Atomsk (optional)</h3>
                <div className="chip-row">
                  <span className="chip">
                    <span className="chip-k">atomsk</span>
                    <span className={`chip-v ${engines?.atomsk_found ? "tone-ok" : "tone-warn"}`}>
                      {engines?.atomsk_found ? "found" : "optional"}
                    </span>
                  </span>
                </div>
                <p className="hint">{engines?.atomsk_path || "Polycrystal seeds work without Atomsk"}</p>
              </div>
            </div>
            <pre className="log" style={{ height: "auto" }}>
{`# Prefer setup_and_run.cmd (installs LAMMPS + clones KART if missing)

# Crystal-aware lattices: bcc | fcc | hcp | diamond | hex(WC)
# OVITO DXA (easiest): pip install -U ovito   OR set AEGIS_OVITO_BIN=…/ovitos.exe
# Optional: pip install ase · atomsk for GB rebuilds`}
            </pre>
          </section>
        )}
      </main>
      <aside className="recipe" aria-label="Run recipe summary">
        <p className="eyebrow">Selected recipe</p>
        <h2>{projectName || "Untitled study"}</h2>
        <dl>
          <div>
            <dt>Material</dt>
            <dd>{material?.name || "Not selected"}</dd>
          </div>
          <div>
            <dt>Potential</dt>
            <dd className={!selectedPot?.available && !selectedPot?.is_placeholder ? "tone-fail" : selectedPot?.is_placeholder ? "tone-warn" : ""}>
              {selectedPot?.name || "Not selected"}
            </dd>
          </div>
          <div>
            <dt>Scenario</dt>
            <dd>{scenario?.fuel || "Custom"} · {params.mode}</dd>
          </div>
          <div>
            <dt>E<sub>PKA</sub></dt>
            <dd>{params.pka_energy_eV.toLocaleString()} eV · {(params.pka_energy_eV / 1000).toLocaleString()} keV</dd>
          </div>
          <div>
            <dt>Temperature</dt>
            <dd>{params.temperature_K.toLocaleString()} K</dd>
          </div>
          <div>
            <dt>Cell</dt>
            <dd>{params.nx} × {params.ny} × {params.nz} unit cells</dd>
          </div>
        </dl>
        <p className="recipe-note">
          D–D and D–T are irradiation scenario presets for cascade or implantation studies, not plasma-scale predictions.
        </p>
      </aside>
    </div>
  );
}
