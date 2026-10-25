"""Optional Neon-backed replay catalog. Falls back cleanly when unavailable."""
import os
from . import db

def enabled():
    return os.environ.get("WATTSNEXT_USE_NEON", "true").lower() in ("1", "true", "yes") and bool(db.database_url())

def load_catalog():
    if not enabled():
        return None
    try:
        import psycopg
        with psycopg.connect(db.database_url(), connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    select h.external_id,h.display_name,h.city,h.case_key,h.declared_needs,h.alert_opt_in,h.alert_channel,
                           c.case_key,c.label,c.storm_setting,c.path_valid,s.external_key,cir.external_key,c.source_note
                    from households h left join replay_cases c on c.case_key=h.case_key
                    left join circuits cir on cir.id=c.circuit_id
                    left join substations s on s.id=cir.substation_id
                """)
                households, cases = {}, {}
                for row in cur.fetchall():
                    hid, display, city, case_key, needs, opt_in, channel, ck, label, storm, valid, substation, circuit, note = row
                    households[hid] = {"household_id": hid, "display_name": display, "city": city, "case_id": case_key, "declared_needs": needs or {}, "alert_opt_in": opt_in, "alert_channel": channel}
                    if ck and ck not in cases:
                        cases[ck] = {"case_id": ck, "label": label, "storm_setting": storm, "substation": substation, "circuit": circuit, "cities": [city], "path_valid": valid, "damage_items": [], "source_note": note}
                cur.execute("select replay_case_id,asset_type,quantity,size_kva,status,quarantined from damage_records")
                damage_rows = cur.fetchall()
                cur.execute("select id,case_key from replay_cases")
                ids = {rid: key for rid, key in cur.fetchall()}
                for rid, asset, quantity, size_kva, status, quarantined in damage_rows:
                    key = ids.get(rid)
                    if key and not quarantined:
                        cases[key]["damage_items"].append({"asset_type": asset, "quantity": quantity, "size_kva": size_kva, "repaired": status == "repaired"})
                return households, cases
    except Exception as exc:
        if os.environ.get("WATTSNEXT_DEBUG_NEON"):
            print(f"Neon catalog load failed: {exc}")
        return None
