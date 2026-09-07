"""
Unit tests for Phase 1 -- Exact Artifact Deployment
(deployment/main.py DeploymentOrchestrator._run_from_artifact /
_build_candidate_from_artifact, reached via DeploymentRequest.artifact_dir).

No SSH, no live NetBox: NetBoxClient, DeviceConnector, ContextBuilder,
ConfigGenerator, and PreDeploymentValidator are all injected fakes so these
tests can prove, in isolation, that:
  - a valid artifact deploys the EXACT recorded .cfg content, byte-for-byte
  - a tampered/missing/non-deployable artifact never reaches the deploy
    engine (no SSH attempt) -- the whole batch is blocked before any device
    is touched
  - ContextBuilder / ConfigGenerator / PreDeploymentValidator are never
    invoked in this mode -- the artifact's manifest is authoritative
  - a NetBox device-identity mismatch blocks only that device and never
    silently substitutes a different one
  - --dry-run performs read-only artifact/identity verification but never
    connects over SSH and never touches the CSV->NetBox SoT sync
"""

import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from deployment.artifact_manager import write_manifest
from deployment.device_connector import DeploymentResult
from deployment.main import DeploymentOrchestrator, DeploymentRequest


@dataclass(frozen=True)
class _FakeAssessment:
    """Minimal stand-in for deployment.main.AssessmentResult, just enough for
    write_manifest() (which only reads .device_name / .device / .failure_reason
    via getattr)."""

    device_name: str
    device: Optional[Mapping[str, Any]] = None
    is_candidate: bool = False
    failure_reason: Optional[str] = None


class _CallCountingStage:
    """Stand-in for ContextBuilder / ConfigGenerator / PreDeploymentValidator.
    Records whether ANY method was ever invoked, for the config-regeneration
    protection test -- artifact mode must never call these at all."""

    def __init__(self) -> None:
        self.call_count = 0

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self.call_count += 1
            return None
        return _record


class _FakeNetBoxClient:
    """Serves `dcim/devices/<id>/` lookups from an in-memory table, exactly
    the endpoint shape DeploymentOrchestrator._build_candidate_from_artifact
    calls (matching the project's existing `netbox.get(f"dcim/devices/{id}/")`
    convention used elsewhere, e.g. device_migration/populator.py)."""

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
            "host": "10.0.0.1",
            "username": "u",
            "password": "p",
            "secret": "s",
            "device_type": "cisco_ios",
            "port": 22,
            "timeout": 10,
        }


class _FakeDeviceConnector:
    """Records every deploy() call so tests can prove SSH/config-push was --
    or crucially was NOT -- attempted, and can inspect exactly what config
    content was handed to the deploy engine."""

    def __init__(self, result_status: str = "success"):
        self.deploy_calls: List[Dict[str, Any]] = []
        self.result_status = result_status

    def deploy(self, device_name, connection_details, generated_configuration, save_config=False):
        self.deploy_calls.append({
            "device_name": device_name,
            "connection_details": dict(connection_details),
            "generated_configuration": generated_configuration,
            "save_config": save_config,
        })
        return DeploymentResult(
            device_name=device_name,
            ip_address=connection_details.get("host"),
            connection_status="connected",
            deployment_status=self.result_status,
            commands_sent=1,
            execution_time_seconds=0.01,
            state="DEPLOYED",
        )


def _write_valid_artifact(
    artifact_dir: Path,
    device_id: int = 1,
    device_name: str = "sw-access-01",
    config_content: str = "hostname sw-access-01\n",
) -> None:
    candidates = [
        _FakeAssessment(
            device_name=device_name,
            device={"id": device_id, "last_updated": "2026-01-01T00:00:00Z"},
            is_candidate=True,
        )
    ]
    (artifact_dir / f"{device_name}.cfg").write_text(config_content, encoding="utf-8")
    write_manifest(
        artifact_dir=artifact_dir,
        batch_id="batch-1",
        timestamp=datetime(2026, 1, 1),
        candidates=candidates,
        skipped=[],
    )


def _build_orchestrator(
    netbox_client=None,
    device_connector=None,
    context_builder=None,
    config_generator=None,
    pre_deployment_validator=None,
) -> DeploymentOrchestrator:
    return DeploymentOrchestrator(
        netbox_client=netbox_client if netbox_client is not None else _FakeNetBoxClient({}),
        device_selector=_CallCountingStage(),
        context_builder=context_builder if context_builder is not None else _CallCountingStage(),
        config_generator=config_generator if config_generator is not None else _CallCountingStage(),
        device_connector=device_connector if device_connector is not None else _FakeDeviceConnector(),
        credential_resolver=_FakeCredentialResolver(),
        pre_deployment_validator=pre_deployment_validator if pre_deployment_validator is not None else _CallCountingStage(),
    )


# --------------------------------------------------------------------------
# Test 1 -- Valid artifact loads and deploys successfully
# --------------------------------------------------------------------------
def test_valid_artifact_loads_and_deploys_successfully():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        _write_valid_artifact(artifact_dir)

        netbox = _FakeNetBoxClient({1: {"id": 1, "name": "sw-access-01", "last_updated": "2026-01-01T00:00:00Z"}})
        connector = _FakeDeviceConnector()
        orchestrator = _build_orchestrator(netbox_client=netbox, device_connector=connector)

        request = DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir))
        summary = orchestrator.run(request)

        assert summary.error_message is None
        assert summary.failed_device_count == 0
        assert summary.assessment_passed_count == 1
        assert len(connector.deploy_calls) == 1


# --------------------------------------------------------------------------
# Test 2 -- Tampered config blocks deployment before SSH
# --------------------------------------------------------------------------
def test_tampered_config_blocks_deployment_before_ssh():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        _write_valid_artifact(artifact_dir)

        cfg_path = artifact_dir / "sw-access-01.cfg"
        tampered = cfg_path.read_text(encoding="utf-8").replace("sw-access-01", "sw-access-0X", 1)
        cfg_path.write_text(tampered, encoding="utf-8")

        netbox = _FakeNetBoxClient({1: {"id": 1, "name": "sw-access-01"}})
        connector = _FakeDeviceConnector()
        orchestrator = _build_orchestrator(netbox_client=netbox, device_connector=connector)

        summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

        assert summary.error_message is not None
        assert "verification failed" in summary.error_message.lower()
        assert connector.deploy_calls == []
        assert netbox.get_calls == []  # batch-level abort happens before any per-device identity check


# --------------------------------------------------------------------------
# Test 3 -- Missing manifest fails immediately
# --------------------------------------------------------------------------
def test_missing_manifest_fails_immediately():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)  # no manifest.json, no .cfg files

        connector = _FakeDeviceConnector()
        orchestrator = _build_orchestrator(device_connector=connector)

        summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

        assert summary.error_message is not None
        assert "manifest.json not found" in summary.error_message
        assert connector.deploy_calls == []


# --------------------------------------------------------------------------
# Test 4 -- deployable=false blocks deployment
# --------------------------------------------------------------------------
def test_deployable_false_blocks_deployment():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        skipped = [_FakeAssessment(device_name="sw-access-01", device={"id": 1}, is_candidate=False, failure_reason="bad config")]
        write_manifest(
            artifact_dir=artifact_dir,
            batch_id="batch-all-failed",
            timestamp=datetime(2026, 1, 1),
            candidates=[],
            skipped=skipped,
        )

        connector = _FakeDeviceConnector()
        orchestrator = _build_orchestrator(device_connector=connector)

        summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

        assert summary.error_message is not None
        assert "deployable=false" in summary.error_message
        assert connector.deploy_calls == []


# --------------------------------------------------------------------------
# Test 5 -- Config regeneration protection (the most important test)
# --------------------------------------------------------------------------
def test_config_regeneration_protection_context_builder_config_generator_validator_never_called():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        _write_valid_artifact(artifact_dir)

        netbox = _FakeNetBoxClient({1: {"id": 1, "name": "sw-access-01"}})
        context_builder = _CallCountingStage()
        config_generator = _CallCountingStage()
        pre_deployment_validator = _CallCountingStage()
        orchestrator = _build_orchestrator(
            netbox_client=netbox,
            context_builder=context_builder,
            config_generator=config_generator,
            pre_deployment_validator=pre_deployment_validator,
        )

        summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

        assert summary.error_message is None
        assert context_builder.call_count == 0
        assert config_generator.call_count == 0
        assert pre_deployment_validator.call_count == 0


# --------------------------------------------------------------------------
# Test 6 -- Exact config deployment (byte-identical to the artifact file)
# --------------------------------------------------------------------------
def test_exact_config_content_is_handed_to_deploy_engine():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        exact_content = "hostname sw-access-01\ninterface GigabitEthernet1/0/1\n switchport mode access\n!\n"
        _write_valid_artifact(artifact_dir, config_content=exact_content)

        netbox = _FakeNetBoxClient({1: {"id": 1, "name": "sw-access-01"}})
        connector = _FakeDeviceConnector()
        orchestrator = _build_orchestrator(netbox_client=netbox, device_connector=connector)

        orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

        assert len(connector.deploy_calls) == 1
        assert connector.deploy_calls[0]["generated_configuration"] == exact_content


# --------------------------------------------------------------------------
# Test 7 -- Device identity mismatch blocks that device, no SSH attempt
# --------------------------------------------------------------------------
def test_device_identity_mismatch_blocks_deployment_no_ssh_attempt():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        _write_valid_artifact(artifact_dir, device_id=1, device_name="sw-access-01")

        # NetBox device_id=1 now belongs to a DIFFERENT device than the manifest recorded.
        netbox = _FakeNetBoxClient({1: {"id": 1, "name": "sw-access-99"}})
        connector = _FakeDeviceConnector()
        orchestrator = _build_orchestrator(netbox_client=netbox, device_connector=connector)

        summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

        # Manifest itself was valid -- this is a per-device identity failure, not a batch abort.
        assert summary.error_message is None
        assert connector.deploy_calls == []
        assert summary.failed_device_count == 1
        assert len(summary.results) == 1
        assert "DEVICE_IDENTITY_MISMATCH" in summary.results[0].error_message


def test_device_missing_from_netbox_blocks_deployment_no_ssh_attempt():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        _write_valid_artifact(artifact_dir, device_id=1, device_name="sw-access-01")

        netbox = _FakeNetBoxClient({})  # device_id=1 no longer exists in NetBox
        connector = _FakeDeviceConnector()
        orchestrator = _build_orchestrator(netbox_client=netbox, device_connector=connector)

        summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir)))

        assert summary.error_message is None
        assert connector.deploy_calls == []
        assert summary.failed_device_count == 1
        assert "DEVICE_IDENTITY_MISMATCH" in summary.results[0].error_message


# --------------------------------------------------------------------------
# Test 8 -- Dry run: verification happens, nothing touches infrastructure
# --------------------------------------------------------------------------
def test_dry_run_verifies_but_never_connects_or_syncs():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        _write_valid_artifact(artifact_dir)

        netbox = _FakeNetBoxClient({1: {"id": 1, "name": "sw-access-01"}})
        connector = _FakeDeviceConnector()
        orchestrator = _build_orchestrator(netbox_client=netbox, device_connector=connector)

        # Best-effort structural proof that the implicit CSV->NetBox sync module
        # is never touched in artifact mode: _run_from_artifact contains no
        # reference to it at all (see deployment/main.py), so it can never end
        # up imported as a side effect of this call.
        sync_module_present_before = "import_config_context" in sys.modules

        summary = orchestrator.run(DeploymentRequest(selection_criteria={}, artifact_dir=str(artifact_dir), dry_run=True))

        assert summary.error_message is None
        assert connector.deploy_calls == []  # no SSH connection, no config push
        assert len(netbox.get_calls) == 1  # read-only identity check did happen
        assert len(summary.results) == 1
        assert summary.results[0].state == "DRY_RUN"
        assert ("import_config_context" in sys.modules) == sync_module_present_before


ALL_TESTS = [
    test_valid_artifact_loads_and_deploys_successfully,
    test_tampered_config_blocks_deployment_before_ssh,
    test_missing_manifest_fails_immediately,
    test_deployable_false_blocks_deployment,
    test_config_regeneration_protection_context_builder_config_generator_validator_never_called,
    test_exact_config_content_is_handed_to_deploy_engine,
    test_device_identity_mismatch_blocks_deployment_no_ssh_attempt,
    test_device_missing_from_netbox_blocks_deployment_no_ssh_attempt,
    test_dry_run_verifies_but_never_connects_or_syncs,
]


if __name__ == "__main__":
    for test in ALL_TESTS:
        test()
        print(f"✓ {test.__name__}")
    print("ALL ARTIFACT DEPLOYMENT (PHASE 1) UNIT TESTS PASSED")
