"""
Unit tests for servicenow/maintenance.py - pure logic, no Docker container, no
HTTP server, no real ServiceNow instance required. Each test redirects the
module's STATE_FILE to a fresh temporary file first, so these tests never
read or write real maintenance state and can run safely in any CI environment.
"""

import tempfile
import time
from pathlib import Path

from servicenow import maintenance


def _fresh_state_file():
    """Point the module at a brand-new temp file for one test's duration."""
    tmp_dir = tempfile.mkdtemp(prefix="maintenance_mode_test_")
    maintenance.STATE_FILE = Path(tmp_dir) / "maintenance_state.json"


def test_parse_duration_variants():
    _fresh_state_file()
    assert maintenance.parse_duration_to_seconds("30s") == 30
    assert maintenance.parse_duration_to_seconds("5m") == 300
    assert maintenance.parse_duration_to_seconds("2h") == 7200
    assert maintenance.parse_duration_to_seconds("1d") == 86400
    assert maintenance.parse_duration_to_seconds("120") == 120


def test_parse_duration_invalid_raises():
    _fresh_state_file()
    try:
        maintenance.parse_duration_to_seconds("not-a-duration")
        raise AssertionError("expected MaintenanceModeError for an invalid duration string")
    except maintenance.MaintenanceModeError:
        pass


def test_enable_requires_a_reason():
    _fresh_state_file()
    try:
        maintenance.enable(reason="")
        raise AssertionError("expected MaintenanceModeError when reason is empty")
    except maintenance.MaintenanceModeError:
        pass


def test_global_maintenance_suppresses_any_device():
    _fresh_state_file()
    maintenance.enable(reason="lab shutdown test", duration="10m")
    suppressed, reason = maintenance.is_suppressed(device_name="AnyDevice", site="anysite")
    assert suppressed is True, "global maintenance must suppress every device"
    assert reason is not None and "lab shutdown test" in reason


def test_device_scoped_maintenance_only_covers_named_device():
    _fresh_state_file()
    maintenance.enable(reason="R1 swap", duration="10m", devices=["R1_gns3"])
    suppressed_r1, _ = maintenance.is_suppressed(device_name="R1_gns3", site="hyderabad")
    suppressed_sw1, _ = maintenance.is_suppressed(device_name="SW1_gns3", site="hyderabad")
    assert suppressed_r1 is True, "the explicitly-scoped device must be suppressed"
    assert suppressed_sw1 is False, "an out-of-scope device must NOT be suppressed - this is what proves scoping is real, not a blanket switch"


def test_site_scoped_maintenance_only_covers_named_site():
    _fresh_state_file()
    maintenance.enable(reason="site maintenance", duration="10m", sites=["hyderabad"])
    suppressed_here, _ = maintenance.is_suppressed(device_name="AnyDevice", site="hyderabad")
    suppressed_elsewhere, _ = maintenance.is_suppressed(device_name="AnyDevice", site="other-site")
    assert suppressed_here is True
    assert suppressed_elsewhere is False


def test_maintenance_expiry_auto_disables():
    _fresh_state_file()
    maintenance.enable(reason="short window", duration="1s")
    time.sleep(1.2)
    suppressed, _ = maintenance.is_suppressed(device_name="AnyDevice", site="anysite")
    assert suppressed is False, "an expired maintenance window must not still suppress"
    state = maintenance.status()
    assert state.enabled is False, "status() must self-heal an expired window back to DISABLED"
    assert any(h["action"] == "AUTO_EXPIRED" for h in state.history), "the auto-expiry must be recorded in history for auditability"


def test_grace_period_suppresses_then_expires():
    _fresh_state_file()
    maintenance.set_grace(seconds=1)
    suppressed_during, reason = maintenance.is_suppressed(device_name="AnyDevice", site="anysite")
    assert suppressed_during is True
    assert "grace" in reason.lower()
    time.sleep(1.2)
    suppressed_after, _ = maintenance.is_suppressed(device_name="AnyDevice", site="anysite")
    assert suppressed_after is False, "grace period must lapse and stop suppressing on its own"


def test_disable_applies_startup_grace_by_default():
    _fresh_state_file()
    maintenance.enable(reason="test", duration="10m")
    maintenance.disable(apply_grace=True, grace_seconds=5)
    state = maintenance.status()
    assert state.enabled is False
    assert state.grace_until is not None, "disable() must apply a startup grace period by default"


def test_disable_without_grace_leaves_no_grace_window():
    _fresh_state_file()
    maintenance.enable(reason="test", duration="10m")
    maintenance.disable(apply_grace=False)
    state = maintenance.status()
    assert state.enabled is False
    assert state.grace_until is None, "--no-grace must leave no active suppression window at all"


def test_suppressed_event_is_recorded_for_auditability():
    _fresh_state_file()
    maintenance.enable(reason="test", duration="10m")
    maintenance.record_suppressed_event("SW1_gns3", "NetworkDeviceDown", "test reason")
    state = maintenance.status()
    assert state.suppressed_count == 1, "every suppressed alert must increment the visible counter"
    assert any(h["action"] == "SUPPRESSED_ALERT" for h in state.history)


def test_disabled_by_default_and_nothing_suppressed():
    _fresh_state_file()
    state = maintenance.status()
    assert state.enabled is False, "a freshly-initialized state must default to DISABLED, never silently ON"
    suppressed, reason = maintenance.is_suppressed(device_name="AnyDevice", site="anysite")
    assert suppressed is False
    assert reason is None


ALL_TESTS = [
    test_parse_duration_variants,
    test_parse_duration_invalid_raises,
    test_enable_requires_a_reason,
    test_global_maintenance_suppresses_any_device,
    test_device_scoped_maintenance_only_covers_named_device,
    test_site_scoped_maintenance_only_covers_named_site,
    test_maintenance_expiry_auto_disables,
    test_grace_period_suppresses_then_expires,
    test_disable_applies_startup_grace_by_default,
    test_disable_without_grace_leaves_no_grace_window,
    test_suppressed_event_is_recorded_for_auditability,
    test_disabled_by_default_and_nothing_suppressed,
]


if __name__ == "__main__":
    for test in ALL_TESTS:
        test()
        print(f"✓ {test.__name__}")
    print("ALL MAINTENANCE MODE UNIT TESTS PASSED")
