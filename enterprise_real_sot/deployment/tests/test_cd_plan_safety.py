"""
Unit tests for Phase 3 -- CD Plan Workflow safety guarantees.

.github/workflows/cd-plan.yml runs `deployment/cli.py --devices <criteria>
--dry-run` -- the NORMAL, non-artifact DeploymentOrchestrator.run() path, NOT
the Phase 1 --use-artifact-dir replay path (which already has its own
dry-run coverage in test_artifact_deployment.py). These tests prove, without
any live NetBox or SSH, that this normal planning path:

  - still runs ContextBuilder / ConfigGenerator / PreDeploymentValidator (a
    plan MUST generate and validate real configuration -- unlike the
    artifact-replay path, which must NOT)
  - never calls DeviceConnector.deploy() -- zero SSH, zero Netmiko sessions,
    zero device configuration change -- for ANY device, deployable or excluded
  - still produces a Phase 0 artifact (manifest.json with the correct
    deployable/excluded split, .cfg files, summary.txt)
  - never triggers the CSV->NetBox SoT sync (Stage 0), matching cd-plan.yml's
    deliberate omission of --sync-sot
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from deployment.main import DeploymentOrchestrator, DeploymentRequest
from pre_deployment_validation.report import PreDeploymentValidationReport

R1_GNS3 = {
    "id": 10, "name": "R1_gns3",
    "primary_ip4": {"address": "10.0.0.10/24"},
    "platform": {"slug": "cisco-ios"},
    "device_role": {"slug": "l3-gateway-router"},
}
SW1_GNS3 = {
    "id": 11, "name": "SW1_gns3",
    "primary_ip4": {"address": "10.0.0.11/24"},
    "platform": {"slug": "cisco-ios"},
    "device_role": {"slug": "layer-2-access-switch"},
}


class _FakeDeviceSelector:
    def __init__(self, devices: List[Mapping[str, Any]]):
        self._devices = devices

    def select_devices(self, criteria: Dict[str, Any]) -> List[Mapping[str, Any]]:
        return list(self._devices)


class _RecordingContextBuilder:
    def __init__(self) -> None:
        self.calls = 0

    def build_device_context(self, device: Mapping[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        return {"id": device["id"], "name": device["name"]}


class _RecordingConfigGenerator:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, device_context, requested_protocols, requested_interfaces, excluded_interfaces) -> str:
        self.calls += 1
        return f"hostname {device_context['name']}\n!\n"


class _RecordingPreDeploymentValidator:
    """Fails validation only for the device names listed in `fail_devices`,
    exactly the mechanism a real GNS3-staging plan would use to separate
    deployable candidates from excluded ones."""

    def __init__(self, fail_devices: Optional[List[str]] = None) -> None:
        self.calls = 0
        self._fail_devices = set(fail_devices or [])

    def validate(self, device, device_context, generated_configuration, requested_protocols, requested_interfaces):
        self.calls += 1
        name = device_context["name"]
        if name in self._fail_devices:
            return PreDeploymentValidationReport(
                device_name=name, is_valid=False, total_checks=1, passed_checks=0,
                failed_checks=1, error_messages=["simulated pre-deployment validation failure"],
                check_results=[],
            )
        return PreDeploymentValidationReport(
            device_name=name, is_valid=True, total_checks=1, passed_checks=1,
            failed_checks=0, error_messages=[], check_results=[],
        )


class _FakeCredentialResolver:
    def resolve_connection_details(self, device):
        return {
            "host": "10.0.0.1", "username": "u", "password": "p", "secret": "s",
            "device_type": "cisco_ios", "port": 22, "timeout": 10,
        }


class _RecordingDeviceConnector:
    """Never actually connects -- just records whether it was ever asked to."""

    def __init__(self) -> None:
        self.deploy_calls: List[str] = []

    def deploy(self, device_name, connection_details, generated_configuration, save_config=False):
        self.deploy_calls.append(device_name)
        raise AssertionError("DeviceConnector.deploy() must never be called during a --dry-run CD Plan")


def _build_plan_orchestrator(devices, fail_devices=None):
    context_builder = _RecordingContextBuilder()
    config_generator = _RecordingConfigGenerator()
    validator = _RecordingPreDeploymentValidator(fail_devices=fail_devices)
    connector = _RecordingDeviceConnector()
    orchestrator = DeploymentOrchestrator(
        device_selector=_FakeDeviceSelector(devices),
        context_builder=context_builder,
        config_generator=config_generator,
        pre_deployment_validator=validator,
        credential_resolver=_FakeCredentialResolver(),
        device_connector=connector,
    )
    return orchestrator, context_builder, config_generator, validator, connector


def test_dry_run_plan_never_calls_device_connector_deploy():
    orchestrator, context_builder, config_generator, validator, connector = _build_plan_orchestrator(
        [R1_GNS3, SW1_GNS3]
    )
    request = DeploymentRequest(selection_criteria={"site": "gns3-staging"}, dry_run=True)
    summary = orchestrator.run(request)

    assert connector.deploy_calls == []
    assert context_builder.calls == 2
    assert config_generator.calls == 2
    assert validator.calls == 2
    assert summary.assessment_passed_count == 2


def test_dry_run_plan_writes_phase0_artifact_with_manifest():
    orchestrator, *_ = _build_plan_orchestrator([R1_GNS3, SW1_GNS3])
    request = DeploymentRequest(selection_criteria={"site": "gns3-staging"}, dry_run=True)
    summary = orchestrator.run(request)

    assert summary.artifact_dir is not None
    manifest_path = Path(summary.artifact_dir) / "manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["deployable"] is True
    assert len(manifest["devices"]) == 2
    assert manifest["excluded_devices"] == []
    assert manifest["batch_hash"] is not None
    assert (Path(summary.artifact_dir) / "summary.txt").exists()


def test_dry_run_plan_excludes_failed_device_but_remains_deployable_zero_ssh():
    orchestrator, _, _, _, connector = _build_plan_orchestrator(
        [R1_GNS3, SW1_GNS3], fail_devices=["SW1_gns3"]
    )
    request = DeploymentRequest(selection_criteria={"site": "gns3-staging"}, dry_run=True)
    summary = orchestrator.run(request)

    manifest = json.loads((Path(summary.artifact_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["deployable"] is True
    assert len(manifest["devices"]) == 1
    assert manifest["devices"][0]["device_name"] == "R1_gns3"
    assert len(manifest["excluded_devices"]) == 1
    assert manifest["excluded_devices"][0]["device_name"] == "SW1_gns3"
    # Zero SSH for BOTH the deployable candidate and the excluded device.
    assert connector.deploy_calls == []


def test_dry_run_plan_all_devices_fail_validation_produces_non_deployable_manifest():
    orchestrator, _, _, _, connector = _build_plan_orchestrator(
        [R1_GNS3, SW1_GNS3], fail_devices=["R1_gns3", "SW1_gns3"]
    )
    request = DeploymentRequest(selection_criteria={"site": "gns3-staging"}, dry_run=True)
    summary = orchestrator.run(request)

    manifest = json.loads((Path(summary.artifact_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["deployable"] is False
    assert manifest["devices"] == []
    assert len(manifest["excluded_devices"]) == 2
    assert connector.deploy_calls == []
    # This is exactly the condition cd-plan.yml's "Fail If Plan Is Not
    # Deployable" step gates on.
    assert summary.failed_device_count > 0


def test_dry_run_plan_never_triggers_csv_to_netbox_sot_sync_by_default():
    """cd-plan.yml never passes --sync-sot; DeploymentRequest.sync_sot defaults
    to False, so the CSV->NetBox sync module must never even be imported."""
    sync_module_present_before = "import_config_context" in sys.modules

    orchestrator, *_ = _build_plan_orchestrator([R1_GNS3])
    request = DeploymentRequest(selection_criteria={"site": "gns3-staging"}, dry_run=True)
    orchestrator.run(request)

    assert ("import_config_context" in sys.modules) == sync_module_present_before


ALL_TESTS = [
    test_dry_run_plan_never_calls_device_connector_deploy,
    test_dry_run_plan_writes_phase0_artifact_with_manifest,
    test_dry_run_plan_excludes_failed_device_but_remains_deployable_zero_ssh,
    test_dry_run_plan_all_devices_fail_validation_produces_non_deployable_manifest,
    test_dry_run_plan_never_triggers_csv_to_netbox_sot_sync_by_default,
]


if __name__ == "__main__":
    for test in ALL_TESTS:
        test()
        print(f"✓ {test.__name__}")
    print("ALL CD PLAN SAFETY (PHASE 3) UNIT TESTS PASSED")
