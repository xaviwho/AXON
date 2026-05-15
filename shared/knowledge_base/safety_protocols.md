# Safety Protocols — Placeholder

Per-hazard response procedures consumed by Layer D's RAG retrieval. These
become the human-checkable contract for what the agent recommends. Replace
with the customer's actual safety document during deployment.

## Medical Emergency (person down)

**Trigger:** prone person + chemical/equipment proximity, OR pulse/fall sensor.

**Standard response:**

1. `unlock_entry` to the affected zone for responders.
2. `door_lock` on adjacent zones to contain potentially hazardous atmosphere.
3. `power_cutoff` for hot-plates/furnaces in the zone.
4. `notify_responders` (EHS + 119) with severity ≥4.
5. `display_alert` on console with severity 4 and zone callout.
6. `slice_reshape` to upgrade incident-zone camera bandwidth on eMBB.

**Constraints:** never lock the only egress corridor; if the corridor is the
egress path, keep it unlocked even if it adjoins a hazardous zone.

## Fire / Smoke

**Trigger:** thermal sensor spike + smoke detection, OR vision_class=fire ≥ 0.6.

**Standard response:**

1. `power_cutoff` (zone) — within 100 ms on URLLC.
2. `hvac_isolate` (zone) to prevent smoke propagation.
3. `door_lock` (zone) to contain.
4. `slice_reshape` to prioritize URLLC for the next 60 seconds.
5. `notify_responders` (EHS + 119), severity 4.
6. `display_alert` severity 4.

**Constraints:** if `lab-B` furnace is in active high-temperature run, the
power_cutoff must be followed by inert-atmosphere flush — out of MVP scope;
flag in the rationale.

## Gas Leak

**Trigger:** gas sensor above threshold (placeholder: 25 ppm for combustible
gases, customer-specified).

**Standard response:**

1. `hvac_isolate` (zone) to prevent dispersion.
2. `door_lock` (zone) to contain.
3. `notify_responders` (EHS), severity 3.
4. `display_alert` severity 3.
5. `power_cutoff` for ignition sources in the zone.

**Constraints:** do not isolate HVAC if the affected zone has no occupants;
isolation can concentrate the leak above flammability limits.

## PPE Violation + Equipment In Use

**Trigger:** vision_class=ppe_violation + equipment_in_use in same zone.

**Standard response:**

1. `display_alert` severity 1 to operator console.
2. `notify_responders` (EHS only), severity 1.

**Constraints:** never escalate to power_cutoff or door_lock from a PPE
violation alone — it is informational, not life-safety.
