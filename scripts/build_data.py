"""
One-time ETL: turns the raw AEP data package (aep-data/) into the small,
anonymized JSON files the app actually reads from data/.

Run once from the repo root: python3 scripts/build_data.py
Re-run only if the source package in aep-data/ changes.

No premise IDs, addresses, or precise coordinates are copied into the
output — only city names, circuit-level damage summaries, and labor-hour
reference tables.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _dbf import read_dbf
from _xlsx import read_xlsx

ROOT = pathlib.Path(__file__).parent.parent
AEP = ROOT / "aep-data"
OUT = ROOT / "data"


def build_labor_reference():
    sheet = read_xlsx(AEP / "data" / "Install_Labor_HackOHIO.xlsx")["xl/worksheets/sheet2.xml"]

    def hours(row_idx):
        row = sheet[row_idx]
        return {"install_hours": float(row[-2]), "removal_hours": float(row[-1])}

    ilm_row = read_xlsx(AEP / "data" / "Install_Labor_HackOHIO.xlsx")["xl/worksheets/sheet4.xml"][0]
    ilm = float(ilm_row[1])

    transformer_sizes = {}
    for row_idx in range(13, 25):
        row = sheet[row_idx]
        transformer_sizes[str(row[0])] = {"install_hours": float(row[-2]), "removal_hours": float(row[-1])}

    pole_sizes = {
        "small": hours(8),
        "medium": hours(9),
        "large": hours(10),
    }

    return {
        "indirect_multiplier": ilm,
        "indirect_multiplier_source": (
            "Install_Labor_HackOHIO.xlsx — Indirect labor multiplier (ILM). Applied to "
            "install+removal hours to account for drive time, safety discussion, and setup. "
            "Do not add drive/setup/safety time again on top of this."
        ),
        "categories": {
            "transformer": {
                "unit": "per transformer, by kVA size",
                "evidence": "source_data",
                "sizes": transformer_sizes,
            },
            "pole": {
                "unit": "per pole, by height group",
                "evidence": "source_data",
                "sizes": pole_sizes,
            },
            "fuse_bank": {"unit": "per fuse cutout", "evidence": "source_data", **hours(60)},
            "recloser_bank": {"unit": "per recloser", "evidence": "source_data", **hours(48)},
            "switch": {"unit": "per switch", "evidence": "source_data", **hours(57)},
            "secondary": {"unit": "per secondary conductor attachment", "evidence": "source_data", **hours(51)},
            "primary": {
                "unit": "per primary conductor span",
                "evidence": "assumption",
                "evidence_note": (
                    "The supplied labor workbook has no per-span primary-conductor rate. "
                    "Using the Dead-End (conductor termination) category as the closest "
                    "documented proxy — a stated assumption, not a source rate."
                ),
                **hours(39),
            },
            "capacitor_bank": {
                "unit": "per capacitor bank",
                "evidence": "assumption",
                "evidence_note": "No capacitor-bank rate supplied; using Equipment Lead as a proxy.",
                **hours(30),
            },
            "light": {
                "unit": "per light",
                "evidence": "assumption",
                "evidence_note": "No streetlight rate supplied; using Equipment Lead as a proxy.",
                **hours(30),
            },
            "step_transformer": {
                "unit": "per transformer, by kVA size (step transformers use the same table)",
                "evidence": "assumption",
                "evidence_note": "No step-transformer-specific rate supplied; reusing the distribution transformer table.",
                "sizes": transformer_sizes,
            },
        },
    }


def _circuit_city_map():
    _, xfmr = read_dbf(AEP / "data" / "extracted" / "Data2" / "Transformer_Clip.dbf")
    circuit_map = {}
    for r in xfmr:
        cid = r.get("circuit_id")
        if cid and cid not in circuit_map:
            circuit_map[cid] = (r.get("aep_statio"), r.get("aep_circui"))
    return circuit_map


def build_cases():
    """
    Four replay cases grounded in real circuits from the AEP sample package.
    Each case names a real (station, circuit) pair with its real unrepaired
    damage at extract time (2025-10-24) and the real top cities it serves.
    Household-to-case assignment is a replay assumption (see confidence rules).
    """
    return [
        {
            "case_id": "transformer_roanoke",
            "label": "Transformer damage",
            "storm_setting": "severe",
            "substation": "STATION24",
            "circuit": "CIR114",
            "cities": ["Roanoke", "Hardy", "Boones Mill"],
            "path_valid": True,
            "damage_items": [
                {"asset_type": "transformer", "quantity": 1, "size_kva": 25, "repaired": False},
            ],
            "source_note": (
                "Unrepaired transformer damage on STATION24/CIR114 in the ARCOS damage extract "
                "(arcos_prod_damage_09_28_Clip). 25 kVA is the modal transformer size on this circuit."
            ),
        },
        {
            "case_id": "wirepole_vinton",
            "label": "Primary wire and pole damage",
            "storm_setting": "severe",
            "substation": "STATION29",
            "circuit": "CIR6",
            "cities": ["Vinton", "Goodview", "Blue Ridge"],
            "path_valid": True,
            "damage_items": [
                {"asset_type": "primary", "quantity": 2, "repaired": False},
                {"asset_type": "pole", "quantity": 1, "size_group": "medium", "repaired": False},
            ],
            "source_note": "Unrepaired primary-wire and pole damage on STATION29/CIR6 in the ARCOS damage extract.",
        },
        {
            "case_id": "wire_montvale",
            "label": "Primary wire damage",
            "storm_setting": "moderate",
            "substation": "STATION2",
            "circuit": "CIR60",
            "cities": ["Montvale", "Blue Ridge"],
            "path_valid": True,
            "damage_items": [
                {"asset_type": "primary", "quantity": 2, "repaired": False},
            ],
            "source_note": "Unrepaired primary-wire damage on STATION2/CIR60 in the ARCOS damage extract.",
        },
        {
            "case_id": "calm_roanoke",
            "label": "No recorded damage",
            "storm_setting": "calm",
            "substation": "STATION10",
            "circuit": "CIR95",
            "cities": ["Roanoke"],
            "path_valid": True,
            "damage_items": [],
            "source_note": (
                "STATION10/CIR95 has zero damage records in the ARCOS extract — included deliberately "
                "alongside the Roanoke transformer case to show risk follows the upstream path, not the city name."
            ),
        },
    ]


def build_households():
    return [
        {
            "household_id": "h1",
            "display_name": "Household A",
            "city": "Roanoke",
            "case_id": "transformer_roanoke",
            "declared_needs": {"power_bank": True, "needs_phone_for_work": True, "medical_device": False},
            "alert_opt_in": True,
            "alert_channel": "sms",
        },
        {
            "household_id": "h2",
            "display_name": "Household B",
            "city": "Roanoke",
            "case_id": "transformer_roanoke",
            "declared_needs": {"power_bank": False, "needs_phone_for_work": False, "medical_device": True},
            "alert_opt_in": True,
            "alert_channel": "sms",
        },
        {
            "household_id": "h3",
            "display_name": "Household C",
            "city": "Hardy",
            "case_id": "transformer_roanoke",
            "declared_needs": {"power_bank": False, "needs_phone_for_work": False, "medical_device": False},
            "alert_opt_in": False,
            "alert_channel": "email",
        },
        {
            "household_id": "h4",
            "display_name": "Household D",
            "city": "Vinton",
            "case_id": "wirepole_vinton",
            "declared_needs": {"power_bank": True, "needs_phone_for_work": False, "medical_device": False},
            "alert_opt_in": True,
            "alert_channel": "sms",
        },
        {
            "household_id": "h5",
            "display_name": "Household E",
            "city": "Goodview",
            "case_id": "wirepole_vinton",
            "declared_needs": {"power_bank": False, "needs_phone_for_work": False, "medical_device": True},
            "alert_opt_in": True,
            "alert_channel": "email",
        },
        {
            "household_id": "h6",
            "display_name": "Household F",
            "city": "Blue Ridge",
            "case_id": "wirepole_vinton",
            "declared_needs": {"power_bank": False, "needs_phone_for_work": False, "medical_device": False},
            "alert_opt_in": True,
            "alert_channel": "sms",
        },
        {
            "household_id": "h7",
            "display_name": "Household G",
            "city": "Montvale",
            "case_id": "wire_montvale",
            "declared_needs": {"power_bank": True, "needs_phone_for_work": True, "medical_device": False},
            "alert_opt_in": True,
            "alert_channel": "sms",
        },
        {
            "household_id": "h8",
            "display_name": "Household H",
            "city": "Blue Ridge",
            "case_id": "wire_montvale",
            "declared_needs": {"power_bank": False, "needs_phone_for_work": False, "medical_device": False},
            "alert_opt_in": False,
            "alert_channel": "email",
        },
        {
            "household_id": "h9",
            "display_name": "Household I",
            "city": "Montvale",
            "case_id": "wire_montvale",
            "declared_needs": {"power_bank": False, "needs_phone_for_work": False, "medical_device": True},
            "alert_opt_in": True,
            "alert_channel": "sms",
        },
        {
            "household_id": "h10",
            "display_name": "Household J",
            "city": "Roanoke",
            "case_id": "calm_roanoke",
            "declared_needs": {"power_bank": False, "needs_phone_for_work": False, "medical_device": False},
            "alert_opt_in": True,
            "alert_channel": "sms",
        },
        {
            "household_id": "h11",
            "display_name": "Household K",
            "city": "Roanoke",
            "case_id": "calm_roanoke",
            "declared_needs": {"power_bank": True, "needs_phone_for_work": False, "medical_device": False},
            "alert_opt_in": True,
            "alert_channel": "email",
        },
        {
            "household_id": "h12",
            "display_name": "Household L",
            "city": "Roanoke",
            "case_id": "no_path",
            "declared_needs": {"power_bank": False, "needs_phone_for_work": False, "medical_device": False},
            "alert_opt_in": False,
            "alert_channel": "sms",
        },
    ]


def build_no_path_case():
    return {
        "case_id": "no_path",
        "label": "No validated upstream path",
        "storm_setting": "severe",
        "substation": None,
        "circuit": None,
        "cities": ["Roanoke"],
        "path_valid": False,
        "damage_items": [],
        "source_note": (
            "Synthetic consistency-check failure: this household's premise does not resolve to a "
            "complete upstream chain in matched_upstream.txt. Used to exercise the cannot-predict fallback."
        ),
    }


def main():
    OUT.mkdir(exist_ok=True)

    labor = build_labor_reference()
    (OUT / "labor_reference.json").write_text(json.dumps(labor, indent=2))

    cases = build_cases() + [build_no_path_case()]
    (OUT / "cases.json").write_text(json.dumps(cases, indent=2))

    households = build_households()
    (OUT / "sample.json").write_text(json.dumps({"households": households}, indent=2))

    print(f"Wrote {OUT/'labor_reference.json'}")
    print(f"Wrote {OUT/'cases.json'} ({len(cases)} cases)")
    print(f"Wrote {OUT/'sample.json'} ({len(households)} households)")


if __name__ == "__main__":
    main()
