from __future__ import annotations

import json
from pathlib import Path

from aegis_schema import Material, Potential, Scenario


class DataStore:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.materials_path = data_root / "materials" / "presets.json"
        self.user_materials_path = data_root / "materials" / "user.json"
        self.scenarios_path = data_root / "scenarios" / "presets.json"
        self.catalog_path = data_root / "potentials" / "catalog.json"
        self.user_pots_path = data_root / "potentials" / "user_index.json"
        self.attachments_path = data_root / "potentials" / "attachments.json"
        self.library_path = data_root / "potentials" / "library_index.json"
        self.user_materials_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.user_materials_path.exists():
            self.user_materials_path.write_text("[]", encoding="utf-8")
        if not self.user_pots_path.exists():
            self.user_pots_path.write_text("[]", encoding="utf-8")
        if not self.attachments_path.exists():
            self.attachments_path.write_text("{}", encoding="utf-8")

    def _load_json(self, path: Path) -> list | dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def list_materials(self) -> list[Material]:
        items = self._load_json(self.materials_path)
        user = self._load_json(self.user_materials_path)
        by_id = {m["id"]: Material(**m) for m in items}
        for m in user:
            by_id[m["id"]] = Material(**m)
        return list(by_id.values())

    def get_material(self, material_id: str) -> Material | None:
        for m in self.list_materials():
            if m.id == material_id:
                return m
        return None

    def save_material(self, material: Material) -> Material:
        user: list = self._load_json(self.user_materials_path)
        user = [m for m in user if m.get("id") != material.id]
        user.append(material.model_dump(mode="json"))
        self.user_materials_path.write_text(json.dumps(user, indent=2), encoding="utf-8")
        return material

    def list_scenarios(self) -> list[Scenario]:
        return [Scenario(**s) for s in self._load_json(self.scenarios_path)]

    def _attachments(self) -> dict[str, str]:
        data = self._load_json(self.attachments_path)
        return data if isinstance(data, dict) else {}

    def _set_attachment(self, pot_id: str, rel_path: str) -> None:
        att = self._attachments()
        att[pot_id] = rel_path
        self.attachments_path.write_text(json.dumps(att, indent=2), encoding="utf-8")

    def _refresh_available(self, pot: Potential) -> Potential:
        data = pot.model_dump()
        is_placeholder = bool(data.get("is_placeholder"))
        # Local attachment overrides catalog file_path for curated entries
        att = self._attachments().get(pot.id)
        if att:
            data["file_path"] = att
            is_placeholder = False
        file_path = data.get("file_path")
        if file_path:
            full = self.data_root / file_path
            name = full.name.lower()
            if "placeholder" in name or full.suffix.lower() == ".placeholder":
                is_placeholder = True
            exists = full.exists()
            # Placeholder files exist for pipeline wiring but are not production-ready MD.
            data["available"] = exists and not is_placeholder
            data["is_placeholder"] = is_placeholder
            if is_placeholder and exists and "placeholder" not in " ".join(data.get("warnings") or []).lower():
                data.setdefault("warnings", []).append(
                    "Placeholder coefficients only — dry-run / demo path; upload a published potential for real MD."
                )
        else:
            data["available"] = False
            data["is_placeholder"] = is_placeholder
        return Potential(**data)

    def list_potentials(self) -> list[Potential]:
        curated = [self._refresh_available(Potential(**p)) for p in self._load_json(self.catalog_path)]
        user = [self._refresh_available(Potential(**p)) for p in self._load_json(self.user_pots_path)]
        # Prefer user/nist records when they share an id with curated (shouldn't normally)
        by_id = {p.id: p for p in curated}
        for p in user:
            by_id[p.id] = p
        return list(by_id.values())

    def get_potential(self, potential_id: str) -> Potential | None:
        for p in self.list_potentials():
            if p.id == potential_id:
                return p
        return None

    def add_user_potential(self, pot: Potential) -> Potential:
        user: list = self._load_json(self.user_pots_path)
        user = [p for p in user if p.get("id") != pot.id]
        user.append(pot.model_dump())
        self.user_pots_path.write_text(json.dumps(user, indent=2), encoding="utf-8")
        return self._refresh_available(pot)

    def attach_file(self, pot_id: str, dest_rel: str) -> Potential | None:
        """Attach a real parameter file to an existing catalog/user potential id."""
        base = self.get_potential(pot_id)
        if not base:
            return None
        self._set_attachment(pot_id, dest_rel)
        # Also persist a user shadow so listing survives without re-reading only attachments
        shadow = base.model_dump()
        shadow["file_path"] = dest_rel
        shadow["is_placeholder"] = False
        shadow["available"] = True
        if shadow.get("source") == "curated":
            shadow["source"] = "curated"
        warnings = list(shadow.get("warnings") or [])
        note = "Local file attached — cite the original publication/DOI."
        if note not in warnings:
            warnings = [w for w in warnings if "not bundled" not in w.lower() and "upload required" not in w.lower()]
            warnings.append(note)
        shadow["warnings"] = warnings
        # Keep curated catalog pristine; attachment map provides the file.
        return self._refresh_available(Potential(**shadow))

    def resolve_potential_file(self, pot: Potential) -> Path | None:
        """Return on-disk potential path even for placeholders (dry-run wiring)."""
        att = self._attachments().get(pot.id)
        rel = att or pot.file_path
        if not rel:
            return None
        path = self.data_root / rel
        return path if path.exists() else None

    def installed_library_ids(self) -> set[str]:
        ids: set[str] = set()
        for p in self.list_potentials():
            if p.library_id and p.available:
                ids.add(p.library_id)
            # Heuristic: matching filename already present
            if p.file_path and p.available:
                ids.add(Path(p.file_path).name.lower())
        return ids
