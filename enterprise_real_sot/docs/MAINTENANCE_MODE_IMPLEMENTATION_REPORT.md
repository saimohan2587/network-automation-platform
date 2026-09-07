# Maintenance Mode Implementation Report

## 1. Problem

Intentionally shutting down the laptop hosting the GNS3 lab stops every simulated device at once. Prometheus's SNMP scrape then genuinely fails for all of them, `NetworkDeviceDown` genuinely fires for all of them, and — without this change — every one of those firings would reach the ServiceNow webhook and open a real incident. None of this is a false alert in the monitoring sense (the devices really are unreachable); it's a **false alarm in the operational sense** - a planned event being treated as an unplanned failure.

## 2. Why GNS3/laptop shutdown causes false alerts

The pipeline (SNMP → Prometheus → Alertmanager → ServiceNow) has no concept of "this device is expected to be down right now." `up{job="snmp_devices"} == 0` (the `NetworkDeviceDown` expression, `observability/alerts/alert_rules.yaml:17`) is true whether the cause is a real outage or someone closing their laptop lid. Nothing upstream of the ServiceNow adapter currently distinguishes the two.

## 3. Enterprise equivalent of this problem

This is exactly what enterprise NOC tooling calls a **Maintenance Window** (ServiceNow itself has a native "Maintenance Schedule" concept; Nagios/Icinga call it "scheduled downtime"; PagerDuty/Opsgenie call it "maintenance mode"). The universal pattern is the same one implemented here: monitoring keeps collecting and evaluating normally, but ticket/notification creation is gated by an explicit, time-bound, reason-carrying suppression window scoped to the affected devices/sites.

## 4. Architecture chosen

**Option A — a central maintenance state, checked by the ServiceNow adapter before it decides to create/update an incident** — was selected over the alternatives:

- **Option B (Alertmanager silences)** would suppress the alert notification itself, which conflicts with the explicit requirement to keep `send_resolved: true` and preserve full Prometheus/Alertmanager alert visibility (dashboards, `ALERTS` metric, on-call tooling that reads Alertmanager directly would all go blind too, not just ServiceNow).
- **Option C (Prometheus label-based suppression)** would require editing/relabeling Prometheus config every time maintenance starts or ends, and conflates "should this be evaluated as an alert" with "should this open a ticket" - two different concerns. It also can't be toggled without a Prometheus reload.
- **Option A** cleanly separates the concerns: Prometheus keeps scraping, evaluating, and firing exactly as before (nothing about `alert_rules.yaml`, `prometheus.yml`, or Alertmanager's routing was touched); only the ServiceNow adapter's own incident-creation decision is gated. This satisfies the explicit safety requirement "do not lose Prometheus/Grafana observability data during maintenance" essentially for free, because that data path is never touched.

### A discovery that shaped the implementation

Before writing any code, `docker-compose.yml` was re-inspected together with a live check inside the running container. It confirmed that `observability/docker-compose.yml` mounts `../servicenow:/app/servicenow:ro` (read-only) **except** `servicenow/storage`, which is overridden by a separate named Docker volume (`observability_servicenow_data`) with its own backing store completely outside this repository's working directory. A plain file dropped on the host at `enterprise_real_sot/servicenow/storage/maintenance_state.json` by a host-run CLI script would therefore be **invisible** to the running adapter - two different files, silently out of sync.

To avoid that trap, the CLI does not write any file directly. It talks to the adapter over the same HTTP port it already exposes (`localhost:8000`), and the adapter itself owns reading/writing the state file from inside its own process - where the volume-backed path is correct by construction. This also means the state genuinely persists across a container restart (proven in Test 5 below), because it lives in the same durable volume as `incidents.json`.

## 5. Files Changed

| File | Change |
|---|---|
| `servicenow/maintenance.py` | **New.** Core maintenance-state module: `MaintenanceState` dataclass, JSON persistence, duration parsing (`8h`/`30m`/`45s`/`2d`/bare seconds), `enable()`/`disable()`/`set_grace()`/`status()`, and `is_suppressed(device_name, site)` - the single function the incident pipeline calls. Includes self-healing auto-expiry (a read past `expires_at` flips the state back to disabled and records it), a visible `suppressed_count`, and a capped rolling `history` log. |
| `servicenow/client/servicenow_client.py` | One new check at the top of `process_alert_payload()`: for `alert_status == "firing"` alerts only, calls `maintenance.is_suppressed(...)`; if suppressed, logs it, records it, and returns `("SUPPRESSED_MAINTENANCE", "N/A")` without touching incident storage at all. Resolved alerts are untouched by this change - they always flow through the existing dedup/resolve logic. |
| `servicenow/handlers/webhook_receiver.py` | Added `GET /maintenance/status` and `POST /maintenance/{enable,disable,grace}` routes, reusing the existing `_send_json_response` helper. The `/webhook` route's own logic is unchanged. |
| `maintenance_mode.py` | **New**, repo root. Thin `urllib`-based CLI (`enable`/`disable`/`grace`/`status`) matching the requested command shape exactly; talks to the adapter over HTTP, never touches a file. |
| `docs/MAINTENANCE_MODE_IMPLEMENTATION_REPORT.md` | This report. |

No changes were made to `observability/prometheus/*`, `observability/alertmanager/*`, `observability/snmp_exporter/*`, `deployment/*`, or the rollback implementation.

## 6. Exact Flow Before Maintenance (normal operation, unchanged)

```
Device DOWN (real) → Prometheus fires NetworkDeviceDown → Alertmanager (send_resolved: true)
   → POST /webhook → is_suppressed() returns (False, None) → normal dedup/create logic
   → ServiceNow incident CREATED → email notification (per existing ServiceNow rules)
```

## 7. Exact Flow During Maintenance

```
maintenance_mode.py enable --reason "..." --duration 8h [--device X] [--site Y]
   → POST /maintenance/enable → adapter writes MaintenanceState (enabled=true, scoped or global)

Device DOWN (planned) → Prometheus still fires NetworkDeviceDown (unaffected)
   → Alertmanager still sends it (unaffected) → POST /webhook
   → is_suppressed(device, site) → True → action="SUPPRESSED_MAINTENANCE"
   → NO incident created, NO email sent, suppressed_count incremented, event logged to history
```

A **resolved** alert arriving during maintenance is never suppressed - if a real incident happens to already be open and the alert clears, it is still allowed to resolve normally.

## 8. Exact Flow After Maintenance

```
maintenance_mode.py disable
   → adapter clears enabled=false AND sets grace_until = now + DEVICE_STARTUP_GRACE_PERIOD (default 300s)

Device still booting → Prometheus may still fire NetworkDeviceDown → POST /webhook
   → is_suppressed() checks grace_until FIRST → still True while inside the window
   → suppressed, reason="Startup grace period active until <timestamp>"

Grace window lapses → next alert (if the device is still actually down) is NOT suppressed
   → normal ServiceNow incident creation resumes automatically, no manual action needed
```

`maintenance_mode.py grace --duration N` can also be used standalone (without ever enabling maintenance) for the case of simply restarting the observability stack.

## 9. Commands

```
python3 maintenance_mode.py enable --reason "Planned GNS3 lab shutdown" --duration 8h
python3 maintenance_mode.py enable --reason "SW2 swap" --duration 1h --device SW2_gns3
python3 maintenance_mode.py status
python3 maintenance_mode.py disable
python3 maintenance_mode.py disable --no-grace
python3 maintenance_mode.py grace --duration 300
```

`SERVICENOW_ADAPTER_URL` (env var, default `http://localhost:8000`) lets the CLI target a different adapter address if needed.

## 10. Startup Grace Period Behavior

Configurable via `DEVICE_STARTUP_GRACE_PERIOD` (seconds, default `300`), consumed by `servicenow/maintenance.py`, never hardcoded. Applied automatically on `disable` (unless `--no-grace`), and available standalone via the `grace` subcommand. Uses the exact same `is_suppressed()` check as maintenance mode itself - one suppression mechanism, two independent triggers (explicit maintenance window, or a post-disable/post-restart grace window).

## 11. ServiceNow Impact

No incident is created or updated while suppressed. `suppressed_count` and a rolling `history` (both visible via `status`) give a real, checkable audit trail of exactly what was suppressed and when - maintenance mode is never silent. Real incidents created before or after a maintenance window are completely unaffected; the dedup/create/update/resolve logic in `servicenow_client.py` is otherwise untouched.

## 12. Email Impact

Since suppressed alerts never become incidents, no incident-creation email fires for them either (ServiceNow's own "Monitoring: Network Alert Created" notification only fires on a real incident insert). Real device failures outside any maintenance/grace window still create incidents and still email normally, exactly as before this change.

## 13. Test Results (all performed live, against the real running stack - no mocks)

| # | Scenario | Result |
|---|---|---|
| 1 | Maintenance OFF → firing alert (`SW2_gns3`) | Real incident **created**: `INC0010071` |
| 2 | Maintenance OFF → resolved alert, same fingerprint | **Same** incident `INC0010071` resolved (confirmed via container's live `incidents.json`: `active_incidents` False, `incident_history` state=`Resolved`) |
| 3 | Maintenance ON (global) → firing alert | `action: "SUPPRESSED_MAINTENANCE"`, confirmed **no** incident in `active_incidents` |
| Bonus | Maintenance scoped to `R1_gns3` only → firing alert for `R1_gns3` vs. `SW1_gns3` | `R1_gns3` → suppressed; `SW1_gns3` → real incident **created** (`INC0010072`, then resolved) - proves genuine per-device scoping, not a global/GNS3-specific hack |
| 4 | Maintenance enabled for 2s → wait → status | Auto-flipped to `DISABLED` with an `AUTO_EXPIRED` history entry; next firing alert **created** a real incident (`INC0010073`, then resolved) - confirms automatic resumption, no manual step needed |
| 5 | Enable maintenance → restart `nac_observability_servicenow_adapter` container → status | State **survived the restart** unchanged (same reason, same expiry) - confirmed via the Docker-volume-backed storage path, not the host file |
| 6 | Standalone `grace --duration 3` (no maintenance ever enabled) → firing alert during window vs. after | During: suppressed (`"Startup grace period active until ..."`); after 4s wait: real incident **created** (`INC0010074`, then resolved) |

Full regression: `tests/ci_runner.py` (all 6 CI layers, including the rollback fix from the prior task) still passes end-to-end after these changes. The pre-existing `servicenow/tests/test_servicenow_integration.py` suite was also re-run; 2 of 3 tests pass unchanged, and one (`test_router_assignment_routing`) fails - but this failure is **pre-existing and unrelated to this change**: it exercises `ServiceNowIncidentPayload.from_alertmanager_alert()` directly (a file this task never touched) with `device_role: "edge_router"`, which doesn't match any key in `ASSIGNMENT_GROUPS_BY_ROLE` (`settings.py`, which only has `router`/`routing`/`access`/`switch`/etc.) and falls through to the default assignment group. This is flagged here as a genuine, separate finding rather than silently fixed, since it's outside this task's scope.

## 14. Known Limitations

- Suppression is decided per-alert at the moment it reaches the adapter; there is no retroactive cleanup of an incident that was created a few seconds before maintenance was enabled (a race that would only matter if `enable` is run after the outage has already started reaching ServiceNow - the documented workflow of enabling maintenance *before* shutting the lab down avoids this entirely).
- `is_suppressed()` matching is a simple membership check (`device_name in scope_devices`, `site in scope_sites`); it does not currently support wildcards or hierarchical scopes (e.g. "site X except device Y"). This was left out deliberately per "do not overengineer" - it can be added if a real multi-tier maintenance need arises.
- Maintenance state is per-adapter-process; a future highly-available (multi-replica) adapter deployment would need this moved to a shared store rather than a single process's local file. Not a concern at the current single-instance scale.
