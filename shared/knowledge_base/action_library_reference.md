# Action Library Reference

Auto-generated from `shared/action_library/library.json` by `python -m shared.action_library.generate_docs`. Do not edit by hand.

Layer D selects and parameterizes from this bounded set. It cannot synthesize new actions — adding an entry requires design review.

## `display_alert`

Render a banner alert on the AXON Console.

- **Latency class:** eMBB
- **Permission level:** operator
- **Audit requirements:** none
- **Parameters:**
  - `severity` _integer, required_
  - `message` _string, required_
  - `zone_id` _string, optional_

## `door_lock`

Lock a door or seal a zone perimeter.

- **Latency class:** URLLC
- **Permission level:** operator
- **Audit requirements:** pre_state_snapshot
- **Parameters:**
  - `zone_id` _string, required_

## `door_unlock`

Unlock a door or open a zone perimeter, typically to admit responders.

- **Latency class:** URLLC
- **Permission level:** operator
- **Audit requirements:** pre_state_snapshot, operator_notification
- **Parameters:**
  - `zone_id` _string, required_

## `hvac_isolate`

Isolate HVAC dampers to contain smoke, gas, or contamination in a zone.

- **Latency class:** URLLC
- **Permission level:** admin
- **Audit requirements:** pre_state_snapshot
- **Parameters:**
  - `zone_id` _string, required_

## `notify_responders`

Alert designated responders (EHS, 119) with incident summary.

- **Latency class:** eMBB
- **Permission level:** operator
- **Audit requirements:** recipient_acknowledgement
- **Parameters:**
  - `targets` _array, required_
  - `severity` _integer, required_
  - `message` _string, required_

## `power_cutoff`

Cut electrical power to equipment in a zone.

- **Latency class:** URLLC
- **Permission level:** admin
- **Audit requirements:** pre_state_snapshot, operator_notification
- **Parameters:**
  - `zone_id` _string, required_
  - `equipment_ids` _array, optional_

## `slice_reshape`

Reconfigure HFR Ieum 5G+ slice priorities mid-incident. The novel agentic contribution: closes the loop from action layer back to connectivity.

- **Latency class:** URLLC
- **Permission level:** system
- **Audit requirements:** pre_state_snapshot, operator_notification, network_log_link
- **Parameters:**
  - `slices` _array, required_
  - `duration_seconds` _integer, optional_

## `video_stream_to_responder`

Open a live WebRTC video stream from a specific camera to a responder endpoint.

- **Latency class:** eMBB
- **Permission level:** admin
- **Audit requirements:** responder_session_id
- **Parameters:**
  - `camera_id` _string, required_
  - `responder_id` _string, required_
  - `duration_seconds` _integer, optional_
