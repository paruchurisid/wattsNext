"""Loads the replay cases and sample households. Read-only reference data."""
import json
import pathlib
import os

from backend.neon_cases import load_catalog

DATA = pathlib.Path(__file__).parent.parent / "data"

_cases = {c["case_id"]: c for c in json.loads((DATA / "cases.json").read_text())}
_households = {h["household_id"]: h for h in json.loads((DATA / "sample.json").read_text())["households"]}

_neon_catalog = load_catalog() if os.environ.get("WATTSNEXT_USE_NEON", "false").lower() in ("1", "true", "yes") else None
if _neon_catalog:
    _households, _cases = _neon_catalog


def get_case(case_id):
    return _cases.get(case_id)


def get_household(household_id):
    return _households.get(household_id)


def case_for_household(household_id):
    household = get_household(household_id)
    if household is None:
        return None
    return get_case(household["case_id"])


def list_cities():
    cities = {}
    for h in _households.values():
        cities.setdefault(h["city"], []).append(h["household_id"])
    return cities


def list_households():
    return list(_households.values())
