# Lab Profile — Placeholder

Site-specific RAG context for Layer D. Replace with real lab data per
deployment. Structure preserved so the agent's retrieval queries return
useful chunks even with placeholder content.

## Zones

| zone_id      | name                     | notes                                          |
|--------------|--------------------------|------------------------------------------------|
| lab-A        | Wet chemistry lab        | Fume hoods, organic solvents                   |
| lab-B        | Materials processing     | High-temperature furnaces, inert atmospheres   |
| corridor-1   | Main corridor            | Single egress to stairwell                     |
| storage-1    | Chemical storage         | Flammables cabinet, oxidizers cabinet          |

## Chemicals Inventory (placeholder)

- **lab-A:** acetone, ethanol, hydrochloric acid (1 M), sodium hydroxide pellets
- **lab-B:** argon (cylinder), hydrogen (cylinder, regulated), copper sulfate
- **storage-1:** 5 L acetone, 2 L ethanol, 500 mL hydrofluoric acid (locked)

## Equipment Inventory (placeholder)

- **lab-A:** fume-hood-A1, hot-plate-A1, hot-plate-A2, balance-A1
- **lab-B:** furnace-B1 (max 1200 °C), tube-furnace-B2, vacuum-pump-B1
- **storage-1:** flammables-cabinet-1, oxidizers-cabinet-1

## Occupancy Schedule (placeholder)

- **Mon–Fri 09:00–18:00:** routine occupancy, ≤6 researchers
- **Sat 10:00–14:00:** weekend access by registration only
- **Other times:** restricted; any presence is anomalous

## Notes for Layer D

- `hvac_isolate(zone_id="lab-A")` does not isolate `storage-1` — they share a
  duct only if `building.hvac_partition` says so. Do not assume coupling.
- `door_lock` on `corridor-1` traps occupants; require explicit egress
  alternative before locking.
