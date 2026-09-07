"""
Unit tests for Phase 4 -- Controlled CD Deployment.

.github/workflows/cd-deploy.yml downloads an approved Phase 3 artifact and runs
`deployment/cli.py --use-artifact-dir <dir> --approved-by <actor> --approval-ref
<run URL>` WITHOUT --dry-run -- the same Phase 1 artifact-replay path, now
extended (this phase) to also run post-deployment compliance validation and
write deployment_result.json. post_deployment_validation.main.ComplianceOrchestrator
is faked at the module level (the same way deployment/main.py imports it locally
inside _run_from_artifact), so these tests never touch real SSH or a real
ComplianceOrchestrator, but DO exercise the real DeploymentOrchestrator,
artifact_manager.verify_manifest/write_deployment_result, and the verdict-
preservation logic end to end.

Covers:
  - a non-deployable or missing artifact blocks BEFORE any SSH and BEFORE the
    compliance check is even reached
  - approval metadata (--approved-by/--approval-ref) cannot bypass the
    deployable/manifest safety gate
  - a valid approved artifact drives the deploy path with the EXACT artifact
    config, and only the devices that were actually deployed get verified
  - COMPLIANT / DRIFT / UNREACHABLE verdicts survive into
    DeploymentResult.verification_status AND deployment_result.json verbatim
    -- never collapsed into SUCCESS/FAILED
  - a device whose SSH push itself failed is never sent for verification
"""

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import post_deployment_validation.main as compliance_main_module
from deployment.artifact_manager import write_deployment_result, write_manifest
from deployment.device_connector import DeploymentResult
from deployment.main import DeploymentOrchestrator, DeploymentRequest
from post_deployment_validation.report import (
    ComplianceFieldResult,
    ComplianceSummary,
    DeviceComplianceResult,
    ResourceComplianceResult,
)


@dataclass(frozen=True)
class _FakeAssessment:
    device_name: str
    device: Optional[Mapping[str, Any]] = None
    is_candidate: bool = False
    failure_reason: Optional[str] = None


class _CallCountingStage:
    def __init__(self) -> None:
        self.call_count = 0

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self.call_count += 1
            return None
        return _record


class _FakeNetBoxClient:
    def __init__(self, devices_by_id: Dict[int, Dict[str, Any]]):
        self._devices_by_id = devices_by_id
        self.get_calls: List[str] = []

    def get(self, endpoint: str, params=None):
        self.get_calls.append(endpoint)
        device_id = int(endpoint.strip("/").split("/")[-1])
        if device_id not in self._devices_by_id:
            raise Exception(f"NetBox 404: device id {device_id} not found")
        return self._devices_by_id[device_id]


class _FakeCredentialResolver:
    def resolve_connection_details(self, device):
        return {
            "host": "10.0.0.1", "username": "u", "password": "p", "secret": "s",
            "device_type": "cisco_ios", "port": 22, "timeout": 10,
        }


class _FakeDeviceConnector:
    def __init__(self, result_status: str = "success"):
        self.deploy_calls: List[Dict[str, Any]] = []
        self.result_status = result_status

    def deploy(self, device_name, connection_details, generated_configuration, save_config=False):
        self.deploy_calls.append({"device_name": device_name, "generated_configuration": generated_configuration})
        return DeploymentResult(
            device_name=device_name,
            ip_address=connection_details.get("host"),
            connection_status="connected",
            deployment_status=self.result_status,
            commands_sent=1,
            execution_time_seconds=0.01,
            state="DEPLOYED" if self.result_status == "success" else "DEPLOYMENT_FAILED",
            error_message=None if self.result_status == "success" else "simulated CLI rejection",
        )


def _make_fake_compliance_orchestrator(verdict_by_device: Dict[str, str], call_log: List[List[str]]):
    """Factory returning a class shaped like ComplianceOrchestrator, patched in
    at the module level so deployment/main.py's local `from
    post_deployment_validation.main import ComplianceOrchestrator` picks it up."""

    class _FakeComplianceOrchestrator:
        def __init__(self, netbox_client=None):
            pass

        def evaluate_devices(self, devices, request):
            call_log.append([d["name"] for d in devices])
            results = []
            for device in devices:
                verdict = verdict_by_device.get(device["name"], "COMPLIANT")
                if verdict == "DRIFT":
                    field = ComplianceFieldResult(field_name="vlan", expected=10, actual=20, status="DRIFT", reason="VLAN mismatch")
                    resource = ResourceComplianceResult(resource_name="vlan", scope_name="global", field_results=[field])
                    results.append(DeviceComplianceResult(device_name=device["name"], ip_address="10.0.0.1", resource_results=[resource]))
                elif verdict == "UNREACHABLE":
                    results.append(DeviceComplianceResult(
                        device_name=device["name"], ip_address="10.0.0.1", resource_results=[],
                        error_message="Device is unreachable for read-only collection: timed out", unreachable=True,
                    ))
                elif verdict == "FAILED":
                    results.append(DeviceComplianceResult(
                        device_name=device["name"], ip_address="10.0.0.1", resource_results=[],
                        error_message="Compliance evaluation failed: unexpected error",
                    ))
                else:
                    results.append(DeviceComplianceResult(device_name=device["name"], ip_address="10.0.0.1", resource_results=[]))

            compliant = sum(1 for r in results if r.overall_status == "COMPLIANT")
            drifted = sum(1 for r in results if r.overall_status == "DRIFT")
            unreachable = sum(1 for r in results if r.overall_status == "UNREACHABLE")
            failed = sum(1 for r in results if r.overall_status == "FAILED")
            return ComplianceSummary(
                selected_device_count=len(devices),
                compliant_device_count=compliant,
                drifted_device_count=drifted,
                failed_device_count=failed,
                results=results,
                unreachable_device_count=unreachable,
            )

    return _FakeComplianceOrchestrator


def _patch_compliance_orchestrator(verdict_by_device: Dict[str, str]):
    call_log: List[List[str]] = []
    fake_cls = _make_fake_compliance_orchestrator(verdict_by_device, call_log)
    original = compliance_main_module.ComplianceOrchestrator
    compliance_main_module.ComplianceOrchestrator = fake_cls
    return original, call_log


def _restore_compliance_orchestrator(original):
    compliance_main_module.ComplianceOrchestrator = original


def _write_valid_artifact(
    artifact_dir: Path,
    device_id: int = 1,
    device_name: str = "R1_gns3",
    config_content: str = "hostname R1_gns3\n!\n",
) -> None:
    candidates = [_FakeAssessment(device_name=device_name, device={"id": device_id}, is_candidate=True)]
    (artifact_dir / f"{device_name}.cfg").write_text(config_content, encoding="utf-8")
    write_manifest(
        artifact_dir=artifact_dir, batch_id=artifact_dir.name, timestamp=datetime(2026, 1, 1),
        candidates=candidates, skipped=[],
    )


def _build_orchestrator(netbox_client, device_connector):
    return DeploymentOrchestrator(
        netbox_client=netbox_client,
        device_selector=_CallCountingStage(),
        context_builder=_CallCountingStage(),
        config_generator=_CallCountingStage(),
        device_connector=device_connector,
        credential_resolver=_FakeCredentialResolver(),
        pre_deployment_validator=_CallCountingStage(),
    )


# --------------------------------------------------------------------------
# Test 1 -- Non-deployable artifact: no SSH, no compliance check, clear failure
# --------------------------------------------------------------------------
def test_non_deployable_artifact_blocks_before_ssh_and_before_compliance_check():
    original, call_log = _patch_compliance_orchestrator({})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            skipped = [_FakeAssessment(device_name="R1_gns3", device={"id": 1}, is_candidate=False, failure_reason="bad config")]
            write_manifest(artifact_dir=artifact_dir, batch_id="batch-all-failed", timestamp=datetime(2026, 1, 1), candidates=[], skipped=skipped)

            connector = _FakeDeviceConnector()
            orchestrator = _build_orchestrator(_FakeNetBoxClient({}), connector)
            summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

            assert summary.error_message is not None
            assert connector.deploy_calls == []
            assert call_log == []  # compliance check never even attempted
    finally:
        _restore_compliance_orchestrator(original)


# --------------------------------------------------------------------------
# Test 2 -- Missing artifact: no SSH, clear failure
# --------------------------------------------------------------------------
def test_missing_artifact_blocks_before_ssh():
    original, call_log = _patch_compliance_orchestrator({})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            connector = _FakeDeviceConnector()
            orchestrator = _build_orchestrator(_FakeNetBoxClient({}), connector)
            summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(Path(tmp))))

            assert summary.error_message is not None
            assert "manifest.json not found" in summary.error_message
            assert connector.deploy_calls == []
            assert call_log == []
    finally:
        _restore_compliance_orchestrator(original)


# --------------------------------------------------------------------------
# Test 3 -- Valid approved artifact: deployment path invoked, exact config used
# --------------------------------------------------------------------------
def test_valid_approved_artifact_invokes_deployment_path_with_correct_config():
    original, call_log = _patch_compliance_orchestrator({"R1_gns3": "COMPLIANT"})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            exact_content = "hostname R1_gns3\ninterface GigabitEthernet0/0\n ip address 10.0.0.1 255.255.255.0\n!\n"
            _write_valid_artifact(artifact_dir, config_content=exact_content)

            netbox = _FakeNetBoxClient({1: {"id": 1, "name": "R1_gns3"}})
            connector = _FakeDeviceConnector()
            orchestrator = _build_orchestrator(netbox, connector)

            summary = orchestrator.run(DeploymentRequest(
                selection_criteria={}, artifact_dir=str(artifact_dir),
                approved_by="alice", approval_ref="https://github.com/org/repo/actions/runs/123",
            ))

            assert summary.error_message is None
            assert len(connector.deploy_calls) == 1
            assert connector.deploy_calls[0]["generated_configuration"] == exact_content
            assert call_log == [["R1_gns3"]]  # exactly the deployed device, nothing re-selected
            assert summary.results[0].approved_by == "alice"
            assert summary.results[0].approval_ref == "https://github.com/org/repo/actions/runs/123"
    finally:
        _restore_compliance_orchestrator(original)


# --------------------------------------------------------------------------
# Test 4 -- Approval metadata cannot bypass the deployable/manifest safety gate
# --------------------------------------------------------------------------
def test_approval_metadata_cannot_bypass_non_deployable_gate():
    original, call_log = _patch_compliance_orchestrator({})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            skipped = [_FakeAssessment(device_name="R1_gns3", device={"id": 1}, is_candidate=False, failure_reason="bad config")]
            write_manifest(artifact_dir=artifact_dir, batch_id="batch-all-failed", timestamp=datetime(2026, 1, 1), candidates=[], skipped=skipped)

            connector = _FakeDeviceConnector()
            orchestrator = _build_orchestrator(_FakeNetBoxClient({}), connector)
            # Even with explicit approval metadata supplied, a non-deployable
            # manifest must still block deployment entirely.
            summary = orchestrator.run(DeploymentRequest(
                selection_criteria={}, artifact_dir=str(artifact_dir),
                approved_by="alice", approval_ref="https://github.com/org/repo/actions/runs/999",
            ))

            assert summary.error_message is not None
            assert connector.deploy_calls == []
    finally:
        _restore_compliance_orchestrator(original)


# --------------------------------------------------------------------------
# Test 5 -- Deployment success + COMPLIANT: correct success, preserved verbatim
# --------------------------------------------------------------------------
def test_deployment_success_and_compliant_verdict_preserved():
    original, call_log = _patch_compliance_orchestrator({"R1_gns3": "COMPLIANT"})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_valid_artifact(artifact_dir)
            netbox = _FakeNetBoxClient({1: {"id": 1, "name": "R1_gns3"}})
            connector = _FakeDeviceConnector()
            orchestrator = _build_orchestrator(netbox, connector)

            summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

            assert summary.results[0].deployment_status == "success"
            assert summary.results[0].verification_status == "COMPLIANT"

            result_json = json.loads((artifact_dir / "deployment_result.json").read_text(encoding="utf-8"))
            assert result_json["results"][0]["deployment_status"] == "success"
            assert result_json["results"][0]["verification_status"] == "COMPLIANT"
    finally:
        _restore_compliance_orchestrator(original)


# --------------------------------------------------------------------------
# Test 6 -- Deployment success + DRIFT: not falsely reported as full success
# --------------------------------------------------------------------------
def test_deployment_success_but_drift_verdict_not_falsely_reported_success():
    original, call_log = _patch_compliance_orchestrator({"R1_gns3": "DRIFT"})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_valid_artifact(artifact_dir)
            netbox = _FakeNetBoxClient({1: {"id": 1, "name": "R1_gns3"}})
            connector = _FakeDeviceConnector()
            orchestrator = _build_orchestrator(netbox, connector)

            summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

            assert summary.results[0].deployment_status == "success"  # SSH push DID succeed
            assert summary.results[0].verification_status == "DRIFT"  # but verification did NOT
            assert summary.results[0].verification_status not in ("SUCCESS", "FAILED", "COMPLIANT")

            result_json = json.loads((artifact_dir / "deployment_result.json").read_text(encoding="utf-8"))
            assert result_json["results"][0]["verification_status"] == "DRIFT"

            # Reuse the existing Phase 2 CLI exit-code helper -- config-push
            # success does not mean the overall CD result is a success.
            from deployment.cli import _exit_code_for
            assert _exit_code_for(summary) != 0
    finally:
        _restore_compliance_orchestrator(original)


# --------------------------------------------------------------------------
# Test 7 -- UNREACHABLE preserved (never collapsed to FAILED)
# --------------------------------------------------------------------------
def test_unreachable_verdict_preserved_through_artifact_mode():
    original, call_log = _patch_compliance_orchestrator({"R1_gns3": "UNREACHABLE"})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_valid_artifact(artifact_dir)
            netbox = _FakeNetBoxClient({1: {"id": 1, "name": "R1_gns3"}})
            connector = _FakeDeviceConnector()
            orchestrator = _build_orchestrator(netbox, connector)

            summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

            assert summary.results[0].verification_status == "UNREACHABLE"
            assert summary.results[0].verification_status != "FAILED"

            from deployment.cli import _exit_code_for
            assert _exit_code_for(summary) != 0
    finally:
        _restore_compliance_orchestrator(original)


# --------------------------------------------------------------------------
# Test 8 -- Deployment (SSH push) failure: propagated, verification skipped
# --------------------------------------------------------------------------
def test_deployment_failure_propagates_and_skips_compliance_check():
    original, call_log = _patch_compliance_orchestrator({"R1_gns3": "COMPLIANT"})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_valid_artifact(artifact_dir)
            netbox = _FakeNetBoxClient({1: {"id": 1, "name": "R1_gns3"}})
            connector = _FakeDeviceConnector(result_status="failed")
            orchestrator = _build_orchestrator(netbox, connector)

            summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

            assert summary.results[0].deployment_status == "failed"
            # A device whose config push failed must never be sent for
            # post-deployment verification -- nothing new was actually applied.
            assert call_log == []

            from deployment.cli import _exit_code_for
            assert _exit_code_for(summary) != 0
    finally:
        _restore_compliance_orchestrator(original)


# --------------------------------------------------------------------------
# Regression: deployment_result.json must reflect --approved-by/--approval-ref
# (these are stamped onto the summary AFTER _run_from_artifact returns, in
# run()'s _apply_approval_metadata step -- the JSON write must happen after
# that, not before, or it silently records null for both fields).
# --------------------------------------------------------------------------
def test_deployment_result_json_reflects_approval_metadata():
    original, call_log = _patch_compliance_orchestrator({"R1_gns3": "COMPLIANT"})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_valid_artifact(artifact_dir)
            netbox = _FakeNetBoxClient({1: {"id": 1, "name": "R1_gns3"}})
            connector = _FakeDeviceConnector()
            orchestrator = _build_orchestrator(netbox, connector)

            orchestrator.run(DeploymentRequest(
                selection_criteria={}, artifact_dir=str(artifact_dir),
                approved_by="octocat", approval_ref="https://github.com/org/repo/actions/runs/555",
            ))

            payload = json.loads((artifact_dir / "deployment_result.json").read_text(encoding="utf-8"))
            assert payload["results"][0]["approved_by"] == "octocat"
            assert payload["results"][0]["approval_ref"] == "https://github.com/org/repo/actions/runs/555"
    finally:
        _restore_compliance_orchestrator(original)


# --------------------------------------------------------------------------
# write_deployment_result() direct unit test
# --------------------------------------------------------------------------
def test_write_deployment_result_records_exact_fields():
    @dataclass(frozen=True)
    class _FakeSummary:
        selected_device_count: int
        succeeded_device_count: int
        failed_device_count: int
        results: List[DeploymentResult]

    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        result = DeploymentResult(
            device_name="R1_gns3", ip_address="10.0.0.1", connection_status="connected",
            deployment_status="success", commands_sent=2, execution_time_seconds=0.2,
            verification_status="DRIFT", approved_by="alice", approval_ref="run-1",
        )
        summary = _FakeSummary(selected_device_count=1, succeeded_device_count=1, failed_device_count=0, results=[result])

        path = write_deployment_result(artifact_dir, summary)
        assert path == artifact_dir / "deployment_result.json"

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["selected_device_count"] == 1
        assert payload["results"][0]["device_name"] == "R1_gns3"
        assert payload["results"][0]["deployment_status"] == "success"
        assert payload["results"][0]["verification_status"] == "DRIFT"
        assert payload["results"][0]["approved_by"] == "alice"
        assert payload["results"][0]["approval_ref"] == "run-1"


ALL_TESTS = [
    test_non_deployable_artifact_blocks_before_ssh_and_before_compliance_check,
    test_missing_artifact_blocks_before_ssh,
    test_valid_approved_artifact_invokes_deployment_path_with_correct_config,
    test_approval_metadata_cannot_bypass_non_deployable_gate,
    test_deployment_success_and_compliant_verdict_preserved,
    test_deployment_success_but_drift_verdict_not_falsely_reported_success,
    test_unreachable_verdict_preserved_through_artifact_mode,
    test_deployment_failure_propagates_and_skips_compliance_check,
    test_deployment_result_json_reflects_approval_metadata,
    test_write_deployment_result_records_exact_fields,
]


if __name__ == "__main__":
    for test in ALL_TESTS:
        test()
        print(f"✓ {test.__name__}")
    print("ALL CD DEPLOY SAFETY (PHASE 4) UNIT TESTS PASSED")
