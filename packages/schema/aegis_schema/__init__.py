from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class FuelScenario(str, Enum):
    DD = "D-D"
    DT = "D-T"
    CUSTOM = "custom"


class Ensemble(str, Enum):
    NVE = "nve"
    NVT = "nvt"


class RunMode(str, Enum):
    CASCADE = "cascade"
    IMPLANT = "implant"
    SURFACE = "surface"  # low-E He/D free-surface MD (Phase-3)
    INTERSTITIAL = "interstitial"  # insert impurities/SIAs along lattice directions


class KmcTier(str, Enum):
    """Post-cascade kinetic evolution path (see docs/kmc.md)."""

    KART = "kart"
    ML_KMC = "ml_kmc"
    STOCHASTIC_CD = "stochastic_cd"
    FIRST_PASSAGE = "first_passage"
    MMONCA_COMPARE = "mmonca_compare"


class KmcProvenance(BaseModel):
    """Provenance for any kMC-tier summary (kart, mmonca, future ML-KMC / CD)."""

    format: str = "aegis-kmc-provenance-v1"
    tier: KmcTier
    synthetic: bool = False
    prefactor_model: Literal["constant", "htst", "composition_polynomial", "unknown"] = "unknown"
    structure_class: Literal["random", "mmc", "as_cascade", "unknown"] = "as_cascade"
    sro_parameters: dict[str, float] | None = None
    trapping_risk: Literal["low", "medium", "high", "unknown"] = "unknown"
    validation_status: Literal[
        "energy_dat", "reference_curve", "stub", "handoff_ready", "unvalidated"
    ] = "unvalidated"
    target_time_s: float = 0.0
    simulated_volume_cm3: float | None = None
    flicker_ratio: float | None = None
    warnings: list[str] = Field(default_factory=list)


class KmcRecommendRequest(BaseModel):
    material_id: str
    target_time_s: float = Field(1.0, ge=0.0)
    temperature_K: float = Field(600.0, ge=1.0)
    run_kart_anneal: bool = False
    run_mmonca_okmc: bool = False
    structure_kind: str = "single_crystal"
    kmc_tier: KmcTier | None = None


class KmcRecommendResponse(BaseModel):
    recommended_tier: KmcTier
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    concentrated_alloy: bool = False
    prefactor_model_hint: str = "unknown"
    trapping_risk_hint: str = "unknown"
    target_time_s: float = 1.0
    temperature_K: float = 600.0


class CrystalSystem(str, Enum):
    BCC = "bcc"
    FCC = "fcc"
    HCP = "hcp"
    DIAMOND = "diamond"
    HEX = "hex"  # WC-like hexagonal
    OTHER = "other"


class StructureKind(str, Enum):
    SINGLE_CRYSTAL = "single_crystal"
    POLYCRYSTAL = "polycrystal"
    BICRYSTAL = "bicrystal"
    VOID = "void"
    VOID_LATTICE = "void_lattice"
    POLYCRYSTAL_VOID = "polycrystal_void"
    NANOWIRE = "nanowire"
    PRECIPITATE = "precipitate"
    IMPORT = "import"


class ElementFraction(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=3)
    atomic_percent: float = Field(..., ge=0, le=100)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        s = str(v or "").strip()
        if not s:
            raise ValueError("element symbol required")
        if len(s) == 1:
            return s.upper()
        return s[0].upper() + s[1:].lower()


class Material(BaseModel):
    id: str
    name: str
    description: str = ""
    crystal: CrystalSystem | str = CrystalSystem.BCC
    lattice_constant_A: float = 3.165
    lattice_c_A: float | None = None  # HCP / hex c axis
    c_over_a: float | None = None  # optional; derived into lattice_c_A when needed
    composition: list[ElementFraction]
    tags: list[str] = Field(default_factory=list)
    metadata_only: bool = False

    @field_validator("composition")
    @classmethod
    def composition_sums(cls, v: list[ElementFraction]) -> list[ElementFraction]:
        total = sum(e.atomic_percent for e in v)
        if v and abs(total - 100.0) > 0.05:
            raise ValueError(f"composition must sum to 100 at%, got {total}")
        return v

    @field_validator("crystal", mode="before")
    @classmethod
    def normalize_crystal(cls, v: Any) -> str:
        if v is None:
            return CrystalSystem.BCC.value
        key = str(getattr(v, "value", v)).strip().lower()
        aliases = {"wc": "hex", "dia": "diamond", "diamond_cubic": "diamond"}
        return aliases.get(key, key)


class MaterialUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    crystal: CrystalSystem | str | None = None
    lattice_constant_A: float | None = None
    lattice_c_A: float | None = None
    c_over_a: float | None = None
    composition: list[ElementFraction] | None = None
    tags: list[str] | None = None


class PotentialFormalism(str, Enum):
    EAM = "eam"
    EAM_ALLOY = "eam/alloy"
    EAM_FS = "eam/fs"
    MEAM = "meam"
    SNAP = "snap"
    TABLE = "table"
    OTHER = "other"


class Potential(BaseModel):
    id: str
    name: str
    formalism: PotentialFormalism
    elements: list[str]
    recommended_for: list[str] = Field(default_factory=list)
    citation: str = ""
    doi: str = ""
    source_url: str = ""
    warnings: list[str] = Field(default_factory=list)
    lammps_pair_style: str
    pair_coeff_template: str
    file_path: str | None = None
    source: str = "curated"  # curated | user | nist | literature
    available: bool = False
    is_placeholder: bool = False
    library_id: str | None = None
    suitability: str | None = None  # unvalidated | cascade_literature | near_equilibrium | ballistic_only
    provenance: dict[str, Any] | None = None
    provenance_path: str | None = None
    pair_coeff_lines: list[str] | None = None  # multi-line hybrid/overlay coeffs


class PotentialUploadMeta(BaseModel):
    name: str
    formalism: PotentialFormalism = PotentialFormalism.EAM_ALLOY
    elements: list[str]
    lammps_pair_style: str = "eam/alloy"
    pair_coeff_template: str = "pair_coeff * * {file} {elements}"
    notes: str = ""
    recommended_for: list[str] = Field(default_factory=lambda: ["cascade"])
    attach_to_id: str | None = None
    doi: str = ""
    citation: str = ""
    source_url: str = ""
    attestation: bool = False
    unpublished_research: bool = False


class PotentialLiteratureRequest(BaseModel):
    """Package published potential file text with DOI/provenance (never invent coeffs)."""

    name: str = ""
    elements: list[str]
    lammps_pair_style: str = "eam/alloy"
    formalism: PotentialFormalism = PotentialFormalism.EAM_ALLOY
    doi: str = ""
    citation: str = ""
    source_url: str = ""
    notes: str = ""
    filename: str = "literature.potential"
    content: str = ""  # published file body pasted from SI / paper
    attestation: bool = False
    unpublished_research: bool = False
    attach_to_id: str | None = None


class PotentialZblPair(BaseModel):
    type_i: int = 1
    type_j: int = 1
    z_i: int
    z_j: int
    cutoff_A: float


class PotentialHybridStitchRequest(BaseModel):
    """Assemble hybrid/overlay host + ZBL from an existing pot + attested published cutoffs."""

    host_potential_id: str
    name: str = ""
    elements: list[str] | None = None
    zbl_pairs: list[PotentialZblPair]
    doi: str = ""
    citation: str = ""
    source_url: str = ""
    notes: str = ""
    attestation: bool = False


class PotentialLibraryEntry(BaseModel):
    id: str
    name: str
    elements: list[str] = Field(default_factory=list)
    pair_style: str = ""
    formalism: str = "other"
    source: str = "nist"
    entry_url: str = ""
    download_url: str | None = None
    filename: str | None = None
    citation: str = ""
    doi: str = ""
    recommended_for: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    pair_coeff_template: str = "pair_coeff * * {file} {elements}"
    maps_to_catalog_id: str | None = None
    downloadable: bool = False
    installed: bool = False


class PotentialDownloadRequest(BaseModel):
    library_id: str | None = None
    url: str | None = None
    attach_to_id: str | None = None
    name: str | None = None
    elements: list[str] | None = None
    lammps_pair_style: str | None = None


class PotentialImportEntryRequest(BaseModel):
    entry_url: str


class PotentialAcquireSuggestion(BaseModel):
    rank: int
    score: float
    action: str  # download | browse | upload | literature
    library_id: str | None = None
    catalog_id: str | None = None
    title: str
    reason: str
    elements: list[str] = Field(default_factory=list)
    downloadable: bool = False
    installed: bool = False
    entry_url: str = ""
    warnings: list[str] = Field(default_factory=list)
    citation: str = ""
    doi: str = ""
    pair_style: str = ""


class PotentialAcquireResponse(BaseModel):
    material_id: str
    elements: list[str]
    has_ready_potential: bool = False
    ready_potential_ids: list[str] = Field(default_factory=list)
    compatible_potential_ids: list[str] = Field(default_factory=list)
    suggestions: list[PotentialAcquireSuggestion] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class Scenario(BaseModel):
    id: str
    fuel: FuelScenario
    label: str
    description: str = ""
    defaults: dict[str, Any] = Field(default_factory=dict)


class LammpsRunParams(BaseModel):
    mode: RunMode = RunMode.CASCADE
    nx: int = Field(8, ge=2, le=64)
    ny: int = Field(8, ge=2, le=64)
    nz: int = Field(8, ge=2, le=64)
    boundary: str = "p p p"
    crystal_orient: str = "100"  # structure-aware: 100/110/111 or basal/prism
    seed: int = 592856
    ensemble: Ensemble = Ensemble.NVE
    temperature_K: float = 300.0
    damp_ps: float = 0.1
    pka_species: str = "W"
    pka_energy_eV: float = 10000.0
    pka_direction: str = "random"  # random | h k l e.g. "1 1 0"
    n_pkas: int = Field(1, ge=1, le=20)
    pka_delay_steps: int = 0
    # PKA site: center | random | coords (fractional box position → nearest lattice site)
    pka_site: str = "center"
    pka_frac_x: float = Field(0.5, ge=0.0, le=1.0)
    pka_frac_y: float = Field(0.5, ge=0.0, le=1.0)
    pka_frac_z: float = Field(0.5, ge=0.0, le=1.0)
    # Auto stage-aware cascade schedule (growth → peak → quench → residual) for OVITO timelines
    cascade_auto_stages: bool = True
    ion_type: str = "He"
    ion_energy_eV: float = 500.0
    ion_count: int = 1
    ion_angle_deg: float = 0.0
    # Phase-3 surface MD
    vacuum_layers: int = Field(4, ge=1, le=32)
    surface_fluence_ions: int = Field(1, ge=1, le=500)
    # Interstitial insertion (not substitutional composition)
    interstitial_species: str = "He"
    interstitial_count: int = Field(1, ge=1, le=64)
    # Crystal-aware directions: 100 | 110 | 111 | basal | c | random | "h k l"
    interstitial_direction: str = "111"
    # octahedral | tetrahedral | dumbbell | crowdion | basal | hexagonal
    interstitial_geometry: str = "octahedral"
    interstitial_offset_A: float | None = None  # dumbbell/crowdion half-separation; default ~0.25 a
    interstitial_energy_eV: float = 0.0  # optional kick along the lattice direction after insert
    # Structure builder (single crystal | polycrystal | bicrystal GB | nano-void | import)
    structure_kind: StructureKind = StructureKind.SINGLE_CRYSTAL
    poly_n_grains: int = Field(4, ge=2, le=64)
    poly_seed: int = 42
    poly_texture: str = "random"  # random | fiber
    # Symmetric tilt bicrystal: misorientation about gb_tilt_axis; grains stacked along gb_normal
    gb_misorientation_deg: float = Field(15.0, ge=0.1, le=90.0)
    gb_tilt_axis: str = "001"  # Miller / 001|011|111 style
    gb_normal: str = "001"  # GB plane normal / merge direction
    void_radius_A: float = Field(5.0, ge=0.5, le=200.0)
    void_count: int = Field(1, ge=1, le=64)
    void_center_frac_x: float = Field(0.5, ge=0.0, le=1.0)
    void_center_frac_y: float = Field(0.5, ge=0.0, le=1.0)
    void_center_frac_z: float = Field(0.5, ge=0.0, le=1.0)
    # Periodic void lattice (structure_kind=void_lattice): voids at subcell centers
    void_lattice_nx: int = Field(2, ge=1, le=16)
    void_lattice_ny: int = Field(2, ge=1, le=16)
    void_lattice_nz: int = Field(2, ge=1, le=16)
    # Nanowire: cylindrical crystal along nanowire_axis with transverse vacuum
    nanowire_radius_A: float = Field(8.0, ge=1.0, le=200.0)
    nanowire_axis: str = "z"  # x | y | z
    nanowire_vacuum_A: float = Field(10.0, ge=0.0, le=200.0)
    # Precipitate(s): spherical second-phase regions (host + precipitate_species)
    precipitate_species: str = "Re"
    precipitate_radius_A: float = Field(5.0, ge=0.5, le=200.0)
    precipitate_count: int = Field(1, ge=1, le=64)
    precipitate_center_frac_x: float = Field(0.5, ge=0.0, le=1.0)
    precipitate_center_frac_y: float = Field(0.5, ge=0.0, le=1.0)
    precipitate_center_frac_z: float = Field(0.5, ge=0.0, le=1.0)
    structure_import_path: str | None = None  # relative to job dir or absolute for import kind
    timestep_fs: float = 0.001
    max_steps: int = 20000
    neighbor_skin: float = 2.0
    thermo_every: int = 100
    dump_every: int = 1000
    dump_style: str = Field("custom", pattern="^custom$")
    restart_every: int = 0
    ws_lattice_A: float | None = None
    cluster_cutoff_A: float = 3.5
    confirm_large: bool = False
    # Optional post-job OVITO DXA
    run_dxa: bool = False


class JobCreate(BaseModel):
    project_name: str = "untitled"
    material_id: str
    material_override: Material | None = None
    potential_id: str
    scenario_id: str = "dt-divertor"
    run_params: LammpsRunParams
    run_kart_anneal: bool = False
    kart_temperature_K: float = 600.0
    kart_max_events: int = 1000
    kart_max_wall_s: float = Field(600.0, ge=1.0, le=86400.0)
    kart_max_kmc_time_s: float = Field(1.0, ge=0.0)
    # DOE: multiple anneal temperatures after the same cascade (overrides single T when set)
    kart_anneal_temperatures: list[float] | None = None
    run_mmonca_okmc: bool = False
    mmonca_temperature_K: float = 600.0
    mmonca_max_events: int = 1000
    # Optional override; null → router picks at job start
    kmc_tier: KmcTier | None = None
    # Phase F: write constant-ν and hTST handoffs side-by-side
    kart_prefactor_compare: bool = False


class KartAnnealRequest(BaseModel):
    """Re-anneal an existing cascade at one or more temperatures (Phase-2 DOE)."""

    temperature_K: float = 600.0
    max_events: int = Field(1000, ge=1, le=1_000_000)
    max_wall_s: float = Field(600.0, ge=1.0, le=86400.0)
    max_kmc_time_s: float = Field(1.0, ge=0.0)
    temperatures: list[float] | None = None
    prefactor_compare: bool = False


class MlKmcAnnealRequest(BaseModel):
    """Rigid-lattice ML-KMC anneal on an existing cascade job (Phase E)."""

    temperature_K: float = Field(900.0, ge=1.0)
    n_steps: int = Field(200, ge=1, le=1_000_000)
    structure_class: Literal["random", "mmc"] = "random"
    nu_model: Literal["constant", "composition_polynomial"] = "composition_polynomial"
    onnx_path: str | None = None
    seed: int = 1


class ClusterDynamicsRequest(BaseModel):
    """Stochastic cluster dynamics on a completed cascade (Phase G)."""

    temperature_K: float = Field(600.0, ge=1.0)
    target_time_s: float = Field(1e6, ge=0.0)
    volume_cm3: float = Field(1e-9, gt=0.0)
    max_events: int = Field(5000, ge=1, le=10_000_000)
    catalog_path: str | None = None
    seed: int = 1

class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    ANALYZING = "analyzing"
    ANNEALING = "annealing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobInfo(BaseModel):
    id: str
    status: JobStatus
    project_name: str
    material_id: str
    potential_id: str
    scenario_id: str
    created_at: str
    updated_at: str
    message: str = ""
    run_params: LammpsRunParams
    run_kart_anneal: bool = False
    run_mmonca_okmc: bool = False
    kmc_tier: KmcTier | None = None
    defect_summary: dict[str, Any] | None = None
    kart_summary: dict[str, Any] | None = None
    mmonca_summary: dict[str, Any] | None = None
    ml_kmc_summary: dict[str, Any] | None = None
    cd_summary: dict[str, Any] | None = None
    kps_summary: dict[str, Any] | None = None
    kmc_provenance: KmcProvenance | None = None
    surface_summary: dict[str, Any] | None = None
    # Provenance for Results / UI badges
    execution_mode: str | None = None  # real_md | synthetic_proxy
    structure_provenance: dict[str, Any] | None = None


class EngineStatus(BaseModel):
    lammps_found: bool
    lammps_path: str | None = None
    lammps_version: str | None = None
    kart_root: str | None = None
    kart_found: bool
    kart_binary: str | None = None
    kart_commit_expected: str = "62d66adf"
    kart_message: str = ""
    mmonca_found: bool = False
    mmonca_path: str | None = None
    mmonca_message: str = ""
    ml_kmc_onnx_found: bool = False
    ml_kmc_onnx_path: str | None = None
    onnxruntime_found: bool = False
    ml_kmc_message: str = ""
    ase_found: bool = False
    ase_message: str = ""
    ovito_found: bool = False
    ovito_path: str | None = None
    ovito_message: str = ""
    ovito_mode: str = ""
    ovito_version: str | None = None
    atomsk_found: bool = False
    atomsk_path: str | None = None


class DoeAxis(str, Enum):
    TEMPERATURE_K = "temperature_K"
    PKA_ENERGY_EV = "pka_energy_eV"
    ION_ENERGY_EV = "ion_energy_eV"
    N_PKAS = "n_pkas"
    ION_COUNT = "ion_count"
    SURFACE_FLUENCE = "surface_fluence_ions"
    INTERSTITIAL_COUNT = "interstitial_count"


class DoeCampaignCreate(BaseModel):
    """DEMO-facing parameter sweep: Cartesian product of two axes (capped)."""

    name: str = "doe-campaign"
    base: JobCreate
    axis_x: DoeAxis = DoeAxis.PKA_ENERGY_EV
    values_x: list[float] = Field(default_factory=lambda: [5000.0, 10000.0, 20000.0])
    axis_y: DoeAxis | None = DoeAxis.TEMPERATURE_K
    values_y: list[float] | None = Field(default_factory=lambda: [300.0, 600.0, 800.0])
    max_jobs: int = Field(12, ge=1, le=36)
    run_locally: bool = True


class DoeCase(BaseModel):
    job_id: str | None = None
    label: str
    overrides: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"


class DoeCampaignInfo(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    status: str = "queued"
    message: str = ""
    axis_x: str
    values_x: list[float]
    axis_y: str | None = None
    values_y: list[float] | None = None
    cases: list[DoeCase] = Field(default_factory=list)
    job_ids: list[str] = Field(default_factory=list)
    summary_rows: list[dict[str, Any]] = Field(default_factory=list)


class HpcExportRequest(BaseModel):
    scheduler: Literal["slurm", "pbs"] = "slurm"
    cores: int = Field(8, ge=1, le=256)
    walltime: str = "04:00:00"
    account: str = ""
    queue: str = ""
    lammps_module: str = ""
    lammps_bin: str = "lmp"
