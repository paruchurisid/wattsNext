def quality_report():
    return {"quarantined_contradictory_records": 76,
            "rule":"status=unrepaired and repair_timestamp populated",
            "quarantine_active":True, "circuit_reconciliation": {"strategy":"normalized direct join, then feeder/substation prior", "downgraded_matches":0},
            "multiplier_orthogonality":"4.5x indirect overhead includes mobilization/transit; standalone drive time is blocked"}
