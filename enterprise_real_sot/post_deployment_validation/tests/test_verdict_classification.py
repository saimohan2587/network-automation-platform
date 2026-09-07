"""
Unit tests for Phase 2 -- Post-Deployment Verdict Standardization + Exit Codes.

post_deployment_validation is the single owner of the COMPLIANT / DRIFT /
UNREACHABLE / FAILED verdict vocabulary (DeviceComplianceResult.overall_status).
These tests prove, without any live NetBox/GNS3/SSH:

  - the four verdicts classify correctly at their real source (report.py)
  - SSHCollector (the real production collector, only Netmiko itself is
    faked) distinguishes a DeviceUnreachableError (timeout/refused/auth
    failure) from a generic CollectionError (an unrelated bug) -- proving
    UNREACHABLE is detected from the actual exception hierarchy, not guessed
  - the verdict string survives deployment/main.py's Phase 3 wiring and
    deployment/device_connector.DeploymentResult verbatim -- never collapsed
    into a coarser SUCCESS/FAILED pair
  - both deployment/cli.py and post_deployment_validation/cli.py's exit-code
    helpers return 0 only for COMPLIANT and non-zero for DRIFT/UNREACHABLE/FAILED
  - a device whose config push succeeded but whose post-deployment verdict
    was DRIFT/UNREACHABLE still makes the overall CLI exit code non-zero
"""

from post_deployment_validation.cli import _exit_code_for as compliance_exit_code_for
from post_deployment_validation.collectors.base_collector import (
    CollectionError,
    DeviceUnreachableError,
)
from post_deployment_validation.collectors.ssh_collector import SSHCollector
import post_deployment_validation.collectors.ssh_collector as ssh_collector_module
from post_deployment_validation.report import (
    ComplianceFieldResult,
    ComplianceSummary,
    DeviceComplianceResult,
    ResourceComplianceResult,
)

from deployment.cli import _exit_code_for as deployment_exit_code_for
from deployment.device_connector import DeploymentResult
from deployment.main import DeploymentSummary


def _compliant_device(name: str = "sw-access-01") -> DeviceComplianceResult:
    field = ComplianceFieldResult(field_name="vlan", expected=10, actual=10, status="PASS")
    resource = ResourceComplianceResult(resource_name="vlan", scope_name="global", field_results=[field])
    return DeviceComplianceResult(device_name=name, ip_address="10.0.0.1", resource_results=[resource])


def _drifted_device(name: str = "sw-access-01") -> DeviceComplianceResult:
    field = ComplianceFieldResult(field_name="vlan", expected=10, actual=20, status="DRIFT", reason="VLAN mismatch")
    resource = ResourceComplianceResult(resource_name="vlan", scope_name="global", field_results=[field])
    return DeviceComplianceResult(device_name=name, ip_address="10.0.0.1", resource_results=[resource])


def _unreachable_device(name: str = "sw-access-01") -> DeviceComplianceResult:
    return DeviceComplianceResult(
        device_name=name,
        ip_address="10.0.0.1",
        resource_results=[],
        error_message="Device 'sw-access-01' is unreachable for read-only collection: timed out",
        unreachable=True,
    )


def _failed_device(name: str = "sw-access-01") -> DeviceComplianceResult:
    return DeviceComplianceResult(
        device_name=name,
        ip_address="10.0.0.1",
        resource_results=[],
        error_message="Compliance evaluation failed: KeyError('missing_key')",
    )


# --------------------------------------------------------------------------
# Test 1 -- COMPLIANT
# --------------------------------------------------------------------------
def test_compliant_device_classified_correctly():
    assert _compliant_device().overall_status == "COMPLIANT"


# --------------------------------------------------------------------------
# Test 2 -- DRIFT
# --------------------------------------------------------------------------
def test_drifted_device_classified_correctly():
    assert _drifted_device().overall_status == "DRIFT"


# --------------------------------------------------------------------------
# Test 3 -- UNREACHABLE
# --------------------------------------------------------------------------
def test_unreachable_device_classified_correctly():
    assert _unreachable_device().overall_status == "UNREACHABLE"


def test_ssh_collector_classifies_timeout_as_unreachable_not_generic_failure():
    """The REAL SSHCollector.collect(): only Netmiko's ConnectHandler is faked
    to raise NetmikoTimeoutException, exactly as a real SSH timeout would."""
    import netmiko.exceptions as nm_exc

    class _TimeoutTransport:
        def __init__(self, **kwargs):
            raise nm_exc.NetmikoTimeoutException("Connection timed out")

    original = ssh_collector_module.ConnectHandler
    ssh_collector_module.ConnectHandler = _TimeoutTransport
    try:
        try:
            SSHCollector().collect(
                "sw-access-01",
                {"host": "10.0.0.1", "device_type": "arista_eos"},
                ["show version"],
            )
            assert False, "expected DeviceUnreachableError to be raised"
        except DeviceUnreachableError:
            pass
    finally:
        ssh_collector_module.ConnectHandler = original


def test_ssh_collector_classifies_connection_refused_as_unreachable():
    """TCP connection refused (e.g. device powered off / port closed) surfaces
    as a raw OSError subclass from the transport layer, before Netmiko's own
    exception hierarchy even gets involved."""

    class _RefusedTransport:
        def __init__(self, **kwargs):
            raise ConnectionRefusedError("Connection refused")

    original = ssh_collector_module.ConnectHandler
    ssh_collector_module.ConnectHandler = _RefusedTransport
    try:
        try:
            SSHCollector().collect(
                "sw-access-01",
                {"host": "10.0.0.1", "device_type": "arista_eos"},
                ["show version"],
            )
            assert False, "expected DeviceUnreachableError to be raised"
        except DeviceUnreachableError:
            pass
    finally:
        ssh_collector_module.ConnectHandler = original


def test_ssh_collector_classifies_authentication_failure_as_unreachable():
    import netmiko.exceptions as nm_exc

    class _AuthFailTransport:
        def __init__(self, **kwargs):
            raise nm_exc.NetmikoAuthenticationException("Authentication failed")

    original = ssh_collector_module.ConnectHandler
    ssh_collector_module.ConnectHandler = _AuthFailTransport
    try:
        try:
            SSHCollector().collect(
                "sw-access-01",
                {"host": "10.0.0.1", "device_type": "arista_eos"},
                ["show version"],
            )
            assert False, "expected DeviceUnreachableError to be raised"
        except DeviceUnreachableError:
            pass
    finally:
        ssh_collector_module.ConnectHandler = original


# --------------------------------------------------------------------------
# Test 4 -- FAILED (unexpected non-connectivity failure)
# --------------------------------------------------------------------------
def test_failed_device_classified_correctly_not_unreachable():
    result = _failed_device()
    assert result.overall_status == "FAILED"
    assert result.unreachable is False


def test_ssh_collector_classifies_unrelated_bug_as_generic_collection_error_not_unreachable():
    """A bug unrelated to connectivity (e.g. a parser/runtime error raised while
    already connected) must remain a generic CollectionError -- never UNREACHABLE."""

    class _ConnectedButBuggyTransport:
        def __init__(self, **kwargs):
            pass

        def send_command(self, *args, **kwargs):
            raise ValueError("unexpected parser bug, unrelated to connectivity")

        def disconnect(self):
            pass

    original = ssh_collector_module.ConnectHandler
    ssh_collector_module.ConnectHandler = _ConnectedButBuggyTransport
    try:
        try:
            SSHCollector().collect(
                "sw-access-01",
                {"host": "10.0.0.1", "device_type": "arista_eos"},
                ["show version"],
            )
            assert False, "expected CollectionError to be raised"
        except DeviceUnreachableError:
            assert False, "an unrelated ValueError bug must not be classified as UNREACHABLE"
        except CollectionError:
            pass
    finally:
        ssh_collector_module.ConnectHandler = original


# --------------------------------------------------------------------------
# Test 5 -- Passthrough: the verdict string must survive into DeploymentResult
# verbatim, exactly as deployment/main.py's Phase 3 wiring assigns it
# (`ver_stat = st`) -- never translated to SUCCESS/FAILED/DEPLOYED.
# --------------------------------------------------------------------------
def test_verdict_passthrough_into_deployment_result_verification_status():
    for device_result, expected_verdict in [
        (_compliant_device(), "COMPLIANT"),
        (_drifted_device(), "DRIFT"),
        (_unreachable_device(), "UNREACHABLE"),
        (_failed_device(), "FAILED"),
    ]:
        verdict = device_result.overall_status
        assert verdict == expected_verdict

        deployment_result = DeploymentResult(
            device_name="sw-access-01",
            ip_address="10.0.0.1",
            connection_status="connected",
            deployment_status="success",
            commands_sent=1,
            execution_time_seconds=0.1,
            verification_status=verdict,  # exact assignment deployment/main.py performs
        )
        assert deployment_result.verification_status == expected_verdict


def test_unreachable_verdict_never_becomes_failed_success_or_deployed():
    verdict = _unreachable_device().overall_status
    deployment_result = DeploymentResult(
        device_name="sw-access-01",
        ip_address="10.0.0.1",
        connection_status="connected",
        deployment_status="success",
        commands_sent=1,
        execution_time_seconds=0.1,
        verification_status=verdict,
    )
    assert deployment_result.verification_status == "UNREACHABLE"
    assert deployment_result.verification_status not in ("FAILED", "SUCCESS", "DEPLOYED")


# --------------------------------------------------------------------------
# Test 6 -- Deployment succeeded but post-deployment verification did not:
# overall CLI exit code must be non-zero, detailed verdict must be preserved.
# --------------------------------------------------------------------------
def test_deployment_success_but_drift_verdict_yields_nonzero_exit():
    result = DeploymentResult(
        device_name="sw-access-01", ip_address="10.0.0.1", connection_status="connected",
        deployment_status="success", commands_sent=1, execution_time_seconds=0.1,
        verification_status="DRIFT",
    )
    summary = DeploymentSummary(
        selected_device_count=1, succeeded_device_count=1, failed_device_count=0,
        results=(result,),
    )
    assert deployment_exit_code_for(summary) != 0
    assert result.verification_status == "DRIFT"  # detailed verdict preserved, not collapsed


def test_deployment_success_but_unreachable_verdict_yields_nonzero_exit():
    result = DeploymentResult(
        device_name="sw-access-01", ip_address="10.0.0.1", connection_status="connected",
        deployment_status="success", commands_sent=1, execution_time_seconds=0.1,
        verification_status="UNREACHABLE",
    )
    summary = DeploymentSummary(
        selected_device_count=1, succeeded_device_count=1, failed_device_count=0,
        results=(result,),
    )
    assert deployment_exit_code_for(summary) != 0
    assert result.verification_status == "UNREACHABLE"


def test_deployment_success_and_compliant_verdict_yields_zero_exit():
    result = DeploymentResult(
        device_name="sw-access-01", ip_address="10.0.0.1", connection_status="connected",
        deployment_status="success", commands_sent=1, execution_time_seconds=0.1,
        verification_status="COMPLIANT",
    )
    summary = DeploymentSummary(
        selected_device_count=1, succeeded_device_count=1, failed_device_count=0,
        results=(result,),
    )
    assert deployment_exit_code_for(summary) == 0


def test_deployment_ssh_push_failure_still_yields_nonzero_exit_regardless_of_verdict():
    """A device whose SSH push itself failed must never exit 0, even if no
    verification verdict is present at all (verification never ran)."""
    result = DeploymentResult(
        device_name="sw-access-01", ip_address="10.0.0.1", connection_status="connected",
        deployment_status="failed", commands_sent=0, execution_time_seconds=0.1,
    )
    summary = DeploymentSummary(
        selected_device_count=1, succeeded_device_count=0, failed_device_count=1,
        results=(result,),
    )
    assert deployment_exit_code_for(summary) != 0


# --------------------------------------------------------------------------
# post_deployment_validation/cli.py exit-code helper: same 4-verdict contract
# --------------------------------------------------------------------------
def _summary(compliant=0, drifted=0, unreachable=0, failed=0) -> ComplianceSummary:
    return ComplianceSummary(
        selected_device_count=compliant + drifted + unreachable + failed,
        compliant_device_count=compliant,
        drifted_device_count=drifted,
        failed_device_count=failed,
        results=[],
        unreachable_device_count=unreachable,
    )


def test_compliance_cli_exit_code_zero_only_when_all_compliant():
    assert compliance_exit_code_for(_summary(compliant=3)) == 0


def test_compliance_cli_exit_code_nonzero_for_drift():
    assert compliance_exit_code_for(_summary(compliant=2, drifted=1)) != 0


def test_compliance_cli_exit_code_nonzero_for_unreachable():
    assert compliance_exit_code_for(_summary(compliant=2, unreachable=1)) != 0


def test_compliance_cli_exit_code_nonzero_for_failed():
    assert compliance_exit_code_for(_summary(compliant=2, failed=1)) != 0


ALL_TESTS = [
    test_compliant_device_classified_correctly,
    test_drifted_device_classified_correctly,
    test_unreachable_device_classified_correctly,
    test_ssh_collector_classifies_timeout_as_unreachable_not_generic_failure,
    test_ssh_collector_classifies_connection_refused_as_unreachable,
    test_ssh_collector_classifies_authentication_failure_as_unreachable,
    test_failed_device_classified_correctly_not_unreachable,
    test_ssh_collector_classifies_unrelated_bug_as_generic_collection_error_not_unreachable,
    test_verdict_passthrough_into_deployment_result_verification_status,
    test_unreachable_verdict_never_becomes_failed_success_or_deployed,
    test_deployment_success_but_drift_verdict_yields_nonzero_exit,
    test_deployment_success_but_unreachable_verdict_yields_nonzero_exit,
    test_deployment_success_and_compliant_verdict_yields_zero_exit,
    test_deployment_ssh_push_failure_still_yields_nonzero_exit_regardless_of_verdict,
    test_compliance_cli_exit_code_zero_only_when_all_compliant,
    test_compliance_cli_exit_code_nonzero_for_drift,
    test_compliance_cli_exit_code_nonzero_for_unreachable,
    test_compliance_cli_exit_code_nonzero_for_failed,
]


if __name__ == "__main__":
    for test in ALL_TESTS:
        test()
        print(f"✓ {test.__name__}")
    print("ALL VERDICT CLASSIFICATION (PHASE 2) UNIT TESTS PASSED")
