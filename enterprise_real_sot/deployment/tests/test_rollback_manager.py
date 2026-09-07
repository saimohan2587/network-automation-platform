"""
Unit tests for deployment/rollback_manager.py's decision logic in isolation -
no SSH connection, no device, no Docker. These complement (not replace) the
DeviceConnector-level integration tests in tests/ci_runner.py's Layer 6, which
exercise the same logic through a simulated device connection end-to-end.
This file tests ConfigSectionParser/build_rollback_plan/verify_rollback
directly against hand-crafted "show running-config" text.
"""

from deployment.rollback_manager import (
    ConfigSectionParser,
    build_rollback_plan,
    verify_rollback,
)

SAMPLE_RUNNING_CONFIG = """Building configuration...

Current configuration : 400 bytes
!
hostname SW1
!
interface GigabitEthernet0/1
 shutdown
 negotiation auto
!
interface GigabitEthernet0/2
 description Uplink to core
 no shutdown
!
vlan 10
 name USERS
!
logging host 10.10.10.50
!
end
"""


def test_interface_exists_true_for_present_interface():
    assert ConfigSectionParser.interface_exists(SAMPLE_RUNNING_CONFIG, "GigabitEthernet0/1") is True


def test_interface_exists_false_for_absent_interface():
    assert ConfigSectionParser.interface_exists(SAMPLE_RUNNING_CONFIG, "GigabitEthernet9/9") is False


def test_extract_interface_stanza_returns_exact_original_lines():
    stanza = ConfigSectionParser.extract_interface_stanza(SAMPLE_RUNNING_CONFIG, "GigabitEthernet0/2")
    assert stanza == ["description Uplink to core", "no shutdown"]


def test_vlan_exists_and_name_extraction():
    assert ConfigSectionParser.vlan_exists(SAMPLE_RUNNING_CONFIG, "10") is True
    assert ConfigSectionParser.vlan_exists(SAMPLE_RUNNING_CONFIG, "999") is False
    assert ConfigSectionParser.extract_vlan_name(SAMPLE_RUNNING_CONFIG, "10") == "USERS"


def test_rollback_plan_for_modified_existing_interface():
    """Changing an existing interface's description must restore the ORIGINAL lines, not just negate the new ones."""
    applied = ["interface GigabitEthernet0/2", "description NEW_DESCRIPTION", "exit"]
    commands, sections = build_rollback_plan(SAMPLE_RUNNING_CONFIG, applied)
    assert "interface GigabitEthernet0/2" in commands
    assert "default interface GigabitEthernet0/2" in commands
    assert "description Uplink to core" in commands, "must restore the ORIGINAL description, not merely remove the new one"
    assert "no shutdown" in commands
    assert sections == ["interface GigabitEthernet0/2"]


def test_rollback_plan_for_brand_new_interface_removes_it_entirely():
    """An interface that never existed before must be removed, not 'defaulted' (there's nothing to default to)."""
    applied = ["interface Loopback99", "ip address 1.1.1.1 255.255.255.255", "exit"]
    commands, sections = build_rollback_plan(SAMPLE_RUNNING_CONFIG, applied)
    assert commands == ["no interface Loopback99"]
    assert sections == ["interface Loopback99"]


def test_rollback_plan_for_new_vlan_removes_it():
    applied = ["vlan 100", "name NEWVLAN", "exit"]
    commands, sections = build_rollback_plan(SAMPLE_RUNNING_CONFIG, applied)
    assert commands == ["no vlan 100"]
    assert sections == ["global:vlan 100"]


def test_rollback_plan_for_existing_vlan_restores_original_name():
    applied = ["vlan 10", "name RENAMED", "exit"]
    commands, sections = build_rollback_plan(SAMPLE_RUNNING_CONFIG, applied)
    assert "vlan 10" in commands
    assert "name USERS" in commands, "must restore the ORIGINAL vlan name"
    assert sections == ["global:vlan 10"]


def test_rollback_plan_for_new_global_line_removes_it():
    applied = ["logging host 10.10.10.99"]
    commands, sections = build_rollback_plan(SAMPLE_RUNNING_CONFIG, applied)
    assert commands == ["no logging host 10.10.10.99"]


def test_verify_rollback_passes_when_state_matches():
    """The critical case: verification must PASS only when a fresh live read genuinely matches the pre-change snapshot."""
    sections = ["interface GigabitEthernet0/2"]
    # Live config identical to pre-change - rollback genuinely worked.
    passed, details = verify_rollback(SAMPLE_RUNNING_CONFIG, SAMPLE_RUNNING_CONFIG, sections)
    assert passed is True


def test_verify_rollback_fails_when_state_was_not_actually_restored():
    """
    The single most important test in this file: this is the exact false-success
    scenario the rollback fix exists to prevent. Rollback commands may have been
    "sent successfully", but if the live device still shows the new value, this
    must report FAILED, never PASSED.
    """
    sections = ["interface GigabitEthernet0/2"]
    live_config_still_wrong = SAMPLE_RUNNING_CONFIG.replace(
        "description Uplink to core", "description NEW_DESCRIPTION_STILL_PRESENT"
    )
    passed, details = verify_rollback(live_config_still_wrong, SAMPLE_RUNNING_CONFIG, sections)
    assert passed is False, "verification must catch a rollback that did not actually restore the original state"
    assert "GigabitEthernet0/2" in details


def test_verify_rollback_detects_existence_mismatch():
    """A newly-created interface still present after 'rollback' must fail verification, not just content-mismatch."""
    sections = ["interface Loopback99"]
    live_config_interface_still_exists = SAMPLE_RUNNING_CONFIG + "interface Loopback99\n ip address 1.1.1.1 255.255.255.255\n!\n"
    passed, details = verify_rollback(live_config_interface_still_exists, SAMPLE_RUNNING_CONFIG, sections)
    assert passed is False


def test_verify_rollback_no_sections_checked_is_vacuously_true():
    passed, details = verify_rollback(SAMPLE_RUNNING_CONFIG, SAMPLE_RUNNING_CONFIG, [])
    assert passed is True


ALL_TESTS = [
    test_interface_exists_true_for_present_interface,
    test_interface_exists_false_for_absent_interface,
    test_extract_interface_stanza_returns_exact_original_lines,
    test_vlan_exists_and_name_extraction,
    test_rollback_plan_for_modified_existing_interface,
    test_rollback_plan_for_brand_new_interface_removes_it_entirely,
    test_rollback_plan_for_new_vlan_removes_it,
    test_rollback_plan_for_existing_vlan_restores_original_name,
    test_rollback_plan_for_new_global_line_removes_it,
    test_verify_rollback_passes_when_state_matches,
    test_verify_rollback_fails_when_state_was_not_actually_restored,
    test_verify_rollback_detects_existence_mismatch,
    test_verify_rollback_no_sections_checked_is_vacuously_true,
]


if __name__ == "__main__":
    for test in ALL_TESTS:
        test()
        print(f"✓ {test.__name__}")
    print("ALL ROLLBACK MANAGER UNIT TESTS PASSED")
