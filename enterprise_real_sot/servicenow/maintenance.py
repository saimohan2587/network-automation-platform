"""
Purpose: Central Maintenance Mode / Monitoring Suppression state.

Read by ServiceNowClient.process_alert_payload() before a FIRING alert is
allowed to create or update a ServiceNow incident. Prometheus, Alertmanager,
and Grafana are completely unaffected by this module - metrics keep flowing,
alerts keep firing/resolving, dashboards stay accurate. Only the decision
"should this firing alert be allowed to open/touch a ServiceNow ticket" is
gated here. Resolved alerts are never suppressed by this module - a real,
already-open incident must always be allowed to close.

This is intentionally generic (device-name / site scoping, not a GNS3 check)
so the same mechanism covers one device, several devices, a whole site, or a
full lab/collection shutdown, and scales unchanged as the fleet grows.

State is a single JSON file colocated with servicenow/storage/incidents.json,
so it inherits the same persistent Docker volume mount already used for
incident storage - it survives a container restart for free.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
import logging
import os
import re

from servicenow.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("MaintenanceMode")

STATE_FILE: Path = settings.STORAGE_DIR / "maintenance_state.json"

DEFAULT_MAINTENANCE_DURATION = os.getenv("MAINTENANCE_DEFAULT_DURATION", "4h")
DEFAULT_STARTUP_GRACE_SECONDS = int(os.getenv("DEVICE_STARTUP_GRACE_PERIOD", "300"))

_MAX_HISTORY_ENTRIES = 20

_DURATION_RE = re.compile(r"^(\d+)\s*([smhd]?)$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "": 1}


class MaintenanceModeError(ValueError):
    """Raised for invalid maintenance-mode input (bad duration, etc)."""


def parse_duration_to_seconds(value: str) -> int:
    """Accepts '8h', '30m', '45s', '2d', or a bare integer (seconds)."""
    match = _DURATION_RE.match(value.strip())
    if not match:
        raise MaintenanceModeError(
            f"Invalid duration '{value}'. Use a number optionally suffixed with s/m/h/d, e.g. '8h', '30m', '300'."
        )
    amount, unit = match.groups()
    return int(amount) * _UNIT_SECONDS[unit.lower()]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass
class MaintenanceState:
    enabled: bool = False
    reason: Optional[str] = None
    enabled_at: Optional[str] = None
    expires_at: Optional[str] = None
    scope_devices: List[str] = field(default_factory=list)
    scope_sites: List[str] = field(default_factory=list)
    grace_until: Optional[str] = None
    suppressed_count: int = 0
    history: List[dict] = field(default_factory=list)

    def _record_history(self, action: str, detail: str) -> None:
        self.history.append({"action": action, "detail": detail, "timestamp": _iso(_now())})
        if len(self.history) > _MAX_HISTORY_ENTRIES:
            self.history = self.history[-_MAX_HISTORY_ENTRIES:]


def _load() -> MaintenanceState:
    if not STATE_FILE.exists():
        return MaintenanceState()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return MaintenanceState(**{k: raw.get(k, getattr(MaintenanceState(), k)) for k in MaintenanceState.__dataclass_fields__})
    except Exception as err:
        logger.error("Failed to load maintenance state (%s) - defaulting to DISABLED.", err)
        return MaintenanceState()


def _save(state: MaintenanceState) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, indent=2)


def _auto_expire_if_needed(state: MaintenanceState) -> MaintenanceState:
    """Self-heals an expired maintenance window back to DISABLED on read, so
    the state file never silently claims ENABLED past its own expiry."""
    if state.enabled and state.expires_at:
        if _now() > _parse_iso(state.expires_at):
            logger.info("Maintenance window expired at %s - auto-disabling.", state.expires_at)
            state.enabled = False
            state._record_history("AUTO_EXPIRED", f"Maintenance window (reason: {state.reason}) expired.")
            _save(state)
    return state


def enable(
    reason: str,
    duration: Optional[str] = None,
    devices: Optional[List[str]] = None,
    sites: Optional[List[str]] = None,
) -> MaintenanceState:
    if not reason or not reason.strip():
        raise MaintenanceModeError("A --reason is required to enable maintenance mode (visibility requirement).")

    duration = duration or DEFAULT_MAINTENANCE_DURATION
    seconds = parse_duration_to_seconds(duration)
    now = _now()

    state = _load()
    state.enabled = True
    state.reason = reason.strip()
    state.enabled_at = _iso(now)
    state.expires_at = _iso(now + timedelta(seconds=seconds))
    state.scope_devices = list(devices or [])
    state.scope_sites = list(sites or [])
    state.suppressed_count = 0
    scope_desc = (
        "GLOBAL (all devices)"
        if not state.scope_devices and not state.scope_sites
        else f"devices={state.scope_devices or '-'} sites={state.scope_sites or '-'}"
    )
    state._record_history("ENABLED", f"reason='{state.reason}' expires_at={state.expires_at} scope={scope_desc}")
    _save(state)
    logger.info("Maintenance mode ENABLED. Reason: %s. Expires: %s. Scope: %s", state.reason, state.expires_at, scope_desc)
    return state


def disable(apply_grace: bool = True, grace_seconds: Optional[int] = None) -> MaintenanceState:
    state = _load()
    was_enabled = state.enabled
    state.enabled = False
    state.reason = None
    state.enabled_at = None
    state.expires_at = None
    state.scope_devices = []
    state.scope_sites = []

    if apply_grace:
        grace = grace_seconds if grace_seconds is not None else DEFAULT_STARTUP_GRACE_SECONDS
        state.grace_until = _iso(_now() + timedelta(seconds=grace))
        state._record_history("DISABLED", f"was_enabled={was_enabled}; startup grace period applied for {grace}s")
        logger.info("Maintenance mode DISABLED. Startup grace period active for %ss.", grace)
    else:
        state.grace_until = None
        state._record_history("DISABLED", f"was_enabled={was_enabled}; no grace period applied")
        logger.info("Maintenance mode DISABLED. No grace period applied.")

    _save(state)
    return state


def set_grace(seconds: Optional[int] = None) -> MaintenanceState:
    """Apply a startup grace period independently of enable/disable - covers
    'I just restarted the monitoring stack, devices are still booting'."""
    grace = seconds if seconds is not None else DEFAULT_STARTUP_GRACE_SECONDS
    state = _load()
    state.grace_until = _iso(_now() + timedelta(seconds=grace))
    state._record_history("GRACE_SET", f"startup grace period applied for {grace}s")
    _save(state)
    logger.info("Startup grace period set for %ss (until %s).", grace, state.grace_until)
    return state


def status() -> MaintenanceState:
    return _auto_expire_if_needed(_load())


def is_suppressed(device_name: Optional[str] = None, site: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Returns (suppressed, reason). Called once per FIRING alert, before any
    ServiceNow incident create/update decision is made."""
    state = _auto_expire_if_needed(_load())
    now = _now()

    grace_until = _parse_iso(state.grace_until)
    if grace_until and now < grace_until:
        return True, f"Startup grace period active until {state.grace_until}"

    if not state.enabled:
        return False, None

    scoped = bool(state.scope_devices) or bool(state.scope_sites)
    if not scoped:
        return True, f"Maintenance mode enabled (global) - reason: {state.reason}"

    device_match = bool(device_name) and device_name in state.scope_devices
    site_match = bool(site) and site in state.scope_sites
    if device_match or site_match:
        return True, f"Maintenance mode enabled for this device/site - reason: {state.reason}"

    return False, None


def record_suppressed_event(device_name: str, alert_name: str, reason: str) -> None:
    """Increments the visible suppressed-alert counter and appends a compact
    history entry, so `status` shows real evidence maintenance mode is doing
    something rather than suppressing silently and invisibly."""
    state = _load()
    state.suppressed_count += 1
    state._record_history("SUPPRESSED_ALERT", f"device={device_name} alert={alert_name} reason={reason}")
    _save(state)


def format_status(state: MaintenanceState) -> str:
    lines = [f"MAINTENANCE MODE: {'ENABLED' if state.enabled else 'DISABLED'}"]
    if state.enabled:
        lines.append(f"Reason: {state.reason}")
        lines.append(f"Enabled at: {state.enabled_at}")
        lines.append(f"Expires at: {state.expires_at}")
        if state.scope_devices or state.scope_sites:
            lines.append(f"Scope: devices={state.scope_devices or '-'} sites={state.scope_sites or '-'}")
        else:
            lines.append("Scope: GLOBAL (all devices)")
    else:
        lines.append("Normal ServiceNow incident creation resumed.")

    grace_until = _parse_iso(state.grace_until)
    if grace_until and _now() < grace_until:
        lines.append(f"Startup grace period active until: {state.grace_until}")

    lines.append(f"Alerts suppressed so far (this window): {state.suppressed_count}")

    if state.history:
        lines.append("")
        lines.append("Recent history:")
        for entry in state.history[-5:]:
            lines.append(f"  [{entry['timestamp']}] {entry['action']}: {entry['detail']}")

    return "\n".join(lines)
