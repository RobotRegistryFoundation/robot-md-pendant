# robot-md-pendant ↔ robot-md-gateway integration spec

**Status:** Draft — Plan 3 Task 19 deliverable.
**Targets:** robot-md-gateway v0.3.0+; robot-md-pendant firmware v0.2.0+ (Plan 7).

## Purpose

Define the wire contract between the pendant peripheral (HiTL approval + ESTOP signal source) and the gateway (enforcement authority). The pendant is **not** a decision-making device — its "approve" button is a *signal* the gateway weighs against tier policy + scope. Its ESTOP wire is *preemptive* — the gateway treats a high-priority ESTOP signal as denial of any pending action regardless of other gates.

## Charter alignment

Per spec §3:
- **robot-md-pendant** lives at Layer 3-peripheral. Scope: firmware, button/display, signed heartbeat, operator-presence, physical ESTOP.
- **robot-md-gateway** at Layer 3 weighs pendant signals; never delegates decisions to the pendant.

## Wire contract

### Heartbeat (pendant → gateway)

Every 1 second, the pendant emits a **signed heartbeat** to the gateway over the local bus (USB-CDC or BLE in Plan 7):

```json
{
  "type": "PENDANT_HEARTBEAT",
  "pendant_id": "RHN-000000000007",
  "schema_version": "1.0",
  "timestamp_ms": 1746115200000,
  "operator_present": true,
  "approve_pressed": false,
  "estop_wire_state": "normal",
  "battery_pct": 87,
  "fw_version": "0.2.0",
  "sig": "<ed25519-base64>"
}
```

The signature covers all other fields, canonicalized in lexicographic key order. The pendant's public key is registered with RRF under its RHN.

### Heartbeat staleness rule

If the gateway has not received a verified heartbeat in **3 seconds**, it transitions to **safe-stop**: any in-flight motion completes (or aborts on its bounded action envelope), no new actions accepted. Recovery requires fresh heartbeats; the gateway does not auto-resume on a single heartbeat — the operator must press an explicit **resume** signal (a held approve press for ≥1 second).

### Approval signal (pendant → gateway, opportunistic)

When the operator presses approve, the pendant emits an **APPROVAL_SIGNAL** envelope (signed):

```json
{
  "type": "PENDANT_APPROVAL_SIGNAL",
  "pendant_id": "RHN-000000000007",
  "schema_version": "1.0",
  "timestamp_ms": 1746115203500,
  "approves_msg_id": "msg-abc123",
  "operator_intent": "approve",
  "sig": "<ed25519-base64>"
}
```

The gateway weighs this against any pending HiTL-required action. The signal expires in **30 seconds** if not consumed (replay protection). The pendant SHOULD light its display to confirm receipt.

### ESTOP wire (pendant → gateway, preemptive)

Physical ESTOP is a **hardware-level signal** — a wire that, when pulled low, the gateway interprets as immediate halt-all. It bypasses the application-level heartbeat / approval flow. The gateway's reaction (per cert property SF-001) MUST execute within **100ms** of the wire transitioning. The application-layer heartbeat reports `estop_wire_state: "tripped"` so software has a record, but software latency is irrelevant — the gateway's hardware ESTOP path is what enforces.

### Status response (gateway → pendant)

Once per second, in response to each heartbeat, the gateway replies with a STATUS envelope (unsigned; loopback only):

```json
{
  "type": "GATEWAY_STATUS",
  "schema_version": "1.0",
  "received_heartbeat_at": 1746115200015,
  "current_state": "ready" | "safe_stop" | "estop_active" | "fault",
  "pending_hitl_count": 0,
  "last_action_msg_id": "msg-abc122",
  "last_action_outcome": "ok" | "deny",
  "uptime_seconds": 18342
}
```

The pendant uses this to drive its display.

## Pluggable peripheral protocol

Vendors other than the reference pendant MAY register a pendant-class peripheral with the gateway. The gateway requires:

1. The peripheral's RHN registered with RRF.
2. A capability declaration listing which signal types the peripheral emits (`HEARTBEAT`, `APPROVAL_SIGNAL`, `ESTOP_WIRE`).
3. Heartbeat cadence + staleness threshold parameters.
4. Public-key registration for envelope signing.

The reference pendant's wire contract is the canonical implementation; other peripherals MAY add additional envelope types but MUST NOT remove or alter the heartbeat / approval / ESTOP semantics.

## Out of scope (this spec)

- Firmware bring-up details. (Pendant repo READMEs cover that.)
- Specific BLE / USB-CDC framing. (Plan 7 firmware spec.)
- Multi-pendant arbitration. (Plan 8 if/when needed.)

## References

- Spec §3 — robot-md-pendant + robot-md-gateway charters.
- Spec §5 — Track 2 cert properties SF-001 (ESTOP latency) + SF-002 (network-loss safe-stop).
- Spec §9 — Week 3 row "robot-md-pendant: Gateway integration spec drafted".
