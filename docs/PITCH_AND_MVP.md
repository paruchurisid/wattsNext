# Watt'sNext — pitch and demo runbook

Watt'sNext is a customer-facing storm replay that deflects repetitive Tier-1 IVR and call-center questions while improving clarity, CSAT, and auditability. Python owns every calculation; Gemini is only a semantic renderer.

## Radical epistemic honesty

This is a deterministic historical replay, not a live SCADA, outage, weather, or crew-position feed. The ETL quarantines 76 contradictory damage records and reconciles circuit identifiers with an explicit confidence downgrade. The outbound number validator rejects any language-model number outside the Python whitelist and falls back to a deterministic answer.

## Three-minute demo

1. Select Roanoke / Household A and ask whether power may be lost and how long repairs could take.
2. Show High risk, Medium confidence, and the source/assumption/model-estimate badges.
3. Open Storm Replay; show substation → fuse → transformer order and P10/P50/P90.
4. Apply Block Access: the +3.0 h assumption changes the range and emits ETR_UPDATED.
5. Apply Add Crews to show parallel queue compression, then Finish Repairs for POWER_RESTORED.
6. Open governance endpoints and the audit log to prove validation and fallback behavior.

## Safety boundaries

No health status is inferred, no priority restoration is promised, and no number is presented as utility-confirmed. The model card reports calibration honestly and uses a deterministic fallback when evidence is insufficient.
