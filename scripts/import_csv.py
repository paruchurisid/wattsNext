import csv
import json
import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb


ROOT = Path(__file__).resolve().parents[1]


def load_env():
    for name in (".env.local", ".env"):
        path = ROOT / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"'))
            return


def rows(name):
    with (ROOT / "data" / name).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def null(value):
    return value if value not in (None, "") else None


def json_value(value):
    return Jsonb(json.loads(value) if value not in (None, "") else {})


def main():
    load_env()
    url = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            for r in rows("substations.csv"):
                cur.execute("""
                    insert into substations (external_key, name, territory, source_provenance)
                    values (%s, %s, %s, %s)
                    on conflict (external_key) do update set
                      name=excluded.name, territory=excluded.territory,
                      source_provenance=excluded.source_provenance
                    returning id, external_key
                """, (r["external_key"], r["name"], null(r["territory"]), r["source_provenance"]))

            for r in rows("circuits.csv"):
                cur.execute("""
                    insert into circuits (external_key, substation_id, feeder_prefix,
                      customer_count, asset_density, source_provenance)
                    values (%s, (select id from substations where external_key=%s), %s, %s, %s, %s)
                    on conflict (external_key) do update set
                      substation_id=excluded.substation_id, feeder_prefix=excluded.feeder_prefix,
                      customer_count=excluded.customer_count, asset_density=excluded.asset_density,
                      source_provenance=excluded.source_provenance
                """, (r["external_key"], r["substation_key"], null(r["feeder_prefix"]),
                      int(r["customer_count"]), json_value(r["asset_density"]), r["source_provenance"]))

            for r in rows("replay_cases.csv"):
                cur.execute("""
                    insert into replay_cases (case_key, label, storm_setting, circuit_id, path_valid, source_note)
                    values (%s, %s, %s, (select id from circuits where external_key=%s), %s, %s)
                    on conflict (case_key) do update set label=excluded.label,
                      storm_setting=excluded.storm_setting, circuit_id=excluded.circuit_id,
                      path_valid=excluded.path_valid, source_note=excluded.source_note
                """, (r["case_key"], r["label"], r["storm_setting"], r["circuit_key"],
                      r["path_valid"].lower() == "true", null(r["source_note"])))

            for r in rows("damage_records.csv"):
                cur.execute("""
                    insert into damage_records (source_record_key, replay_case_id, damage_circuit_id,
                      customer_circuit_id, normalized_circuit_id, asset_type, quantity, size_kva, status,
                      repair_timestamp, quarantined, quarantine_reason, reconciliation_confidence, source_payload)
                    values (%s, (select id from replay_cases where case_key=%s), %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s)
                    on conflict (source_record_key) do update set replay_case_id=excluded.replay_case_id,
                      damage_circuit_id=excluded.damage_circuit_id, customer_circuit_id=excluded.customer_circuit_id,
                      normalized_circuit_id=excluded.normalized_circuit_id, asset_type=excluded.asset_type,
                      quantity=excluded.quantity, size_kva=excluded.size_kva, status=excluded.status,
                      repair_timestamp=excluded.repair_timestamp, quarantined=excluded.quarantined,
                      quarantine_reason=excluded.quarantine_reason,
                      reconciliation_confidence=excluded.reconciliation_confidence, source_payload=excluded.source_payload
                """, (r["source_record_key"], r["case_key"], null(r["damage_circuit_id"]),
                      null(r["customer_circuit_id"]), null(r["normalized_circuit_id"]), r["asset_type"],
                      int(r["quantity"]), null(r["size_kva"]), r["status"], null(r["repair_timestamp"]),
                      r["quarantined"].lower() == "true", null(r["quarantine_reason"]),
                      null(r["reconciliation_confidence"]), json_value(r["source_payload"])))

            for r in rows("households.csv"):
                cur.execute("""
                    insert into households (external_id, display_name, city, case_key, declared_needs, alert_opt_in, alert_channel)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict (external_id) do update set display_name=excluded.display_name,
                      city=excluded.city, case_key=excluded.case_key, declared_needs=excluded.declared_needs,
                      alert_opt_in=excluded.alert_opt_in, alert_channel=excluded.alert_channel
                """, (r["external_id"], r["display_name"], r["city"], r["case_key"], json_value(r["declared_needs"]),
                      r["alert_opt_in"].lower() == "true", null(r["alert_channel"])))

            for r in rows("labor_references.csv"):
                cur.execute("""
                    insert into labor_references (asset_type, size_group, size_kva, install_hours,
                      removal_hours, indirect_multiplier, source_provenance)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict (asset_type, size_group, size_kva) do update set
                      install_hours=excluded.install_hours, removal_hours=excluded.removal_hours,
                      indirect_multiplier=excluded.indirect_multiplier,
                      source_provenance=excluded.source_provenance
                """, (r["asset_type"], null(r["size_group"]), null(r["size_kva"]),
                      r["install_hours"], r["removal_hours"], r["indirect_multiplier"], r["source_provenance"]))

        conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
              select json_build_object(
                'substations', (select count(*) from substations),
                'circuits', (select count(*) from circuits),
                'replay_cases', (select count(*) from replay_cases),
                'damage_records', (select count(*) from damage_records),
                'households', (select count(*) from households),
                'labor_references', (select count(*) from labor_references))
            """)
            print(cur.fetchone()[0])


if __name__ == "__main__":
    main()
