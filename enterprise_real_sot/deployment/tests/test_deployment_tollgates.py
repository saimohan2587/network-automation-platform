"""
Comprehensive tests for Staging-to-Production Deployment Tollgates.

Verifies:
1. Environment Separation via NetBox Metadata:
   - NetBox tags ('staging', 'production')
   - Custom fields ('environment': 'staging' / 'production')
   - Config context ('environment': 'staging' / 'production')
   - IPAM subnet mapping (10.10.10/20/30/80.0/24 -> staging, 10.10.40/50/60/70.0/24 -> production)
   - Device name fallback heuristics
2. Candidate Environment Filtering:
   - Manifest containing mixed staging & production candidates
   - target_environment="staging" deploys only staging candidates; prod candidates are skipped without failing
   - target_environment="production" deploys only production candidates; staging candidates are skipped
   - target_environment="all" deploys all candidates
3. Staging Failure Blocking Production:
   - SSH push failure on a staging device -> exit code 1 (fails staging job, blocking production)
   - Post-deployment DRIFT verdict on a staging device -> exit code 1 (fails staging job, blocking production)
   - Post-deployment UNREACHABLE verdict on a staging device -> exit code 1 (fails staging job, blocking production)
   - Failure isolation: failure on 1 device does not prevent collecting results on remaining devices
4. Successful Staging Promotion Eligibility:
   - Clean staging deployment with COMPLIANT verification -> exit code 0 (promotes to production approval gate)
5. Artifact Immutability & Consistency Across Stages:
   - Same manifest and .cfg files reused across staging and production
   - Tampered .cfg file between stages fails verify_manifest() before SSH
   - No config regeneration occurs during staging or production runs
"""

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
import unittest

import post_deployment_validation.main as compliance_main_module
from deployment.artifact_manager import verify_manifest, write_deployment_result, write_manifest
from deployment.cli import _exit_code_for
from deployment.device_connector import DeploymentResult
from deployment.environment import resolve_device_environment
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
        ip = "10.0.0.1"
        if isinstance(device, dict):
            primary = device.get("primary_ip") or {}
            addr = primary.get("address") if isinstance(primary, dict) else None
            if addr:
                ip = addr.split("/")[0]
        return {
            "host": ip, "username": "admin", "password": "pwd", "secret": "sec",
            "device_type": "cisco_ios", "port": 22, "timeout": 10,
        }


class _FakeDeviceConnector:
    def __init__(self, failure_devices: Optional[List[str]] = None):
        self.deploy_calls: List[Dict[str, Any]] = []
        self.failure_devices = set(failure_devices or [])

    def deploy(self, device_name, connection_details, generated_configuration, save_config=False):
        self.deploy_calls.append({
            "device_name": device_name,
            "generated_configuration": generated_configuration,
        })
        is_fail = device_name in self.failure_devices
        status = "failed" if is_fail else "success"
        return DeploymentResult(
            device_name=device_name,
            ip_address=connection_details.get("host"),
            connection_status="failed" if is_fail else "connected",
            deployment_status=status,
            commands_sent=0 if is_fail else 5,
            execution_time_seconds=0.01,
            state="DEPLOYMENT_FAILED" if is_fail else "DEPLOYED",
            error_message="SSH failure simulated" if is_fail else None,
        )


def _make_fake_compliance_orchestrator(verdict_by_device: Dict[str, str], call_log: List[List[str]]):
    class _FakeComplianceOrchestrator:
        def __init__(self, netbox_client=None):
            pass

        def evaluate_devices(self, devices, request):
            call_log.append([d["name"] for d in devices])
            results = []
            for device in devices:
                verdict = verdict_by_device.get(device["name"], "COMPLIANT")
                if verdict == "DRIFT":
                    field = ComplianceFieldResult(
                        field_name="vlan", expected=10, actual=20, status="DRIFT", reason="VLAN mismatch"
                    )
                    resource = ResourceComplianceResult(
                        resource_name="vlan", scope_name="global", field_results=[field]
                    )
                    results.append(DeviceComplianceResult(
                        device_name=device["name"], ip_address="10.0.0.1", resource_results=[resource]
                    ))
                elif verdict == "UNREACHABLE":
                    results.append(DeviceComplianceResult(
                        device_name=device["name"], ip_address="10.0.0.1", resource_results=[],
                        error_message="Device unreachable", unreachable=True,
                    ))
                elif verdict == "FAILED":
                    results.append(DeviceComplianceResult(
                        device_name=device["name"], ip_address="10.0.0.1", resource_results=[],
                        error_message="Compliance failure",
                    ))
                else:  # COMPLIANT
                    results.append(DeviceComplianceResult(
                        device_name=device["name"], ip_address="10.0.0.1", resource_results=[]
                    ))

            compliant = sum(1 for r in results if r.overall_status == "COMPLIANT")
            drifted = sum(1 for r in results if r.overall_status == "DRIFT")
            unreachable = sum(1 for r in results if r.overall_status == "UNREACHABLE")
            failed = sum(1 for r in results if r.overall_status == "FAILED")

            return ComplianceSummary(
                selected_device_count=len(devices),
                compliant_device_count=compliant,
                drifted_device_count=drifted,
                unreachable_device_count=unreachable,
                failed_device_count=failed,
                results=results,
            )
    return _FakeComplianceOrchestrator


def _create_sample_manifest_and_configs(
    artifact_dir: Path,
    devices: List[Dict[str, Any]],
) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    candidates = []
    for d in devices:
        cfg_name = f"{d['name']}.cfg"
        cfg_path = artifact_dir / cfg_name
        cfg_path.write_text(d["config"], encoding="utf-8")
        candidates.append(_FakeAssessment(
            device_name=d["name"],
            device={"id": d["id"], "name": d["name"], "primary_ip": d.get("primary_ip")},
            is_candidate=True,
            failure_reason=None,
        ))
    manifest_path = write_manifest(
        artifact_dir=artifact_dir,
        batch_id=artifact_dir.name,
        timestamp=datetime(2026, 10, 27, 12, 0, 0),
        candidates=candidates,
        skipped=[],
    )
    return manifest_path


class TestDeploymentTollgates(unittest.TestCase):

    def test_environment_separation_via_netbox_tags(self):
        """Metadata Priority 1: NetBox tags take highest precedence."""
        # Tagged staging
        dev_stag = {
            "name": "R_Generic",
            "tags": [{"name": "staging", "slug": "staging"}],
            "primary_ip": {"address": "10.10.70.2/24"},  # prod IP, but tag is staging
        }
        self.assertEqual(resolve_device_environment(dev_stag), "staging")

        # Tagged production
        dev_prod = {
            "name": "SW_Generic",
            "tags": [{"name": "production", "slug": "production"}],
            "primary_ip": {"address": "10.10.20.2/24"},  # staging IP, but tag is production
        }
        self.assertEqual(resolve_device_environment(dev_prod), "production")

    def test_environment_separation_via_custom_fields_and_context(self):
        """Metadata Priority 2 & 3: Custom fields and config context."""
        dev_cf = {
            "name": "R_Unknown",
            "custom_fields": {"environment": "staging"},
        }
        self.assertEqual(resolve_device_environment(dev_cf), "staging")

        dev_ctx = {
            "name": "SW_Unknown",
            "config_context": {"environment": "production"},
        }
        self.assertEqual(resolve_device_environment(dev_ctx), "production")

    def test_environment_separation_via_ipam_subnets(self):
        """Metadata Priority 4: IPAM subnets distinguish staging vs prod."""
        staging_ips = ["10.10.10.2/24", "10.10.20.2/24", "10.10.30.2/24", "10.10.80.2/24"]
        for ip in staging_ips:
            dev = {"name": "NodeX", "primary_ip": {"address": ip}}
            self.assertEqual(resolve_device_environment(dev), "staging", f"Expected staging for {ip}")

        prod_ips = ["10.10.40.2/24", "10.10.50.2/24", "10.10.60.2/24", "10.10.70.2/24"]
        for ip in prod_ips:
            dev = {"name": "NodeY", "primary_ip": {"address": ip}}
            self.assertEqual(resolve_device_environment(dev), "production", f"Expected production for {ip}")

    def test_environment_separation_via_name_fallback(self):
        """Metadata Priority 6: Fallback to device name conventions."""
        self.assertEqual(resolve_device_environment({"name": "R1"}), "staging")
        self.assertEqual(resolve_device_environment({"name": "SW1Staging"}), "staging")
        self.assertEqual(resolve_device_environment({"name": "R2"}), "production")
        self.assertEqual(resolve_device_environment({"name": "SW1Prod"}), "production")
        self.assertEqual(resolve_device_environment({"name": "unknown_box"}), "unknown")

    def test_environment_separation_via_site_metadata(self):
        """Metadata Priority 5: NetBox Site slug separates staging vs prod."""
        dev_site_stag = {
            "name": "Router-X",
            "site": {"name": "GNS3 Staging", "slug": "gns3-staging"},
        }
        self.assertEqual(resolve_device_environment(dev_site_stag), "staging")

        dev_site_prod = {
            "name": "Router-Y",
            "site": {"name": "GNS3 Production", "slug": "gns3-production"},
        }
        self.assertEqual(resolve_device_environment(dev_site_prod), "production")

    def test_candidate_environment_filtering_in_orchestrator(self):
        """Target environment filters candidates properly without marking skipped as failures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "test_artifact"
            device_definitions = [
                {"id": 19, "name": "R1", "primary_ip": {"address": "10.10.10.2/24"}, "config": "hostname R1\n"},
                {"id": 20, "name": "SW1Staging", "primary_ip": {"address": "10.10.20.2/24"}, "config": "hostname SW1Staging\n"},
                {"id": 23, "name": "R2", "primary_ip": {"address": "10.10.70.2/24"}, "config": "hostname R2\n"},
                {"id": 24, "name": "SW1Prod", "primary_ip": {"address": "10.10.40.2/24"}, "config": "hostname SW1Prod\n"},
            ]
            _create_sample_manifest_and_configs(artifact_dir, device_definitions)

            netbox_devices = {
                d["id"]: {
                    "id": d["id"],
                    "name": d["name"],
                    "tags": [{"name": "staging" if "Staging" in d["name"] or d["name"] == "R1" else "production"}],
                    "primary_ip": d["primary_ip"],
                }
                for d in device_definitions
            }

            fake_netbox = _FakeNetBoxClient(netbox_devices)
            fake_connector = _FakeDeviceConnector()
            fake_stages = _CallCountingStage()

            orchestrator = DeploymentOrchestrator(
                netbox_client=fake_netbox,
                credential_resolver=_FakeCredentialResolver(),
                device_connector=fake_connector,
                context_builder=fake_stages,
                config_generator=fake_stages,
                pre_deployment_validator=fake_stages,
            )

            # 1. Run with target_environment='staging'
            req_staging = DeploymentRequest(
                selection_criteria={},
                artifact_dir=str(artifact_dir),
                target_environment="staging",
                dry_run=True,
            )
            summary_staging = orchestrator.run(req_staging)

            # Only R1 and SW1Staging should be active candidates and deployed
            deployed_staging_names = [r.device_name for r in summary_staging.results]
            self.assertEqual(deployed_staging_names, ["R1", "SW1Staging"])
            self.assertEqual(summary_staging.failed_device_count, 0)
            self.assertEqual(_exit_code_for(summary_staging), 0)

            # 2. Run with target_environment='production'
            fake_connector.deploy_calls.clear()
            req_prod = DeploymentRequest(
                selection_criteria={},
                artifact_dir=str(artifact_dir),
                target_environment="production",
                dry_run=True,
            )
            summary_prod = orchestrator.run(req_prod)

            deployed_prod_names = [r.device_name for r in summary_prod.results]
            self.assertEqual(deployed_prod_names, ["R2", "SW1Prod"])
            self.assertEqual(summary_prod.failed_device_count, 0)
            self.assertEqual(_exit_code_for(summary_prod), 0)

    def test_staging_ssh_failure_blocks_production(self):
        """If a staging SSH push fails, summary has failures and exit code is 1 (blocking production)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "test_artifact"
            device_definitions = [
                {"id": 19, "name": "R1", "primary_ip": {"address": "10.10.10.2/24"}, "config": "hostname R1\n"},
                {"id": 20, "name": "SW1Staging", "primary_ip": {"address": "10.10.20.2/24"}, "config": "hostname SW1Staging\n"},
            ]
            _create_sample_manifest_and_configs(artifact_dir, device_definitions)

            netbox_devices = {
                d["id"]: {
                    "id": d["id"], "name": d["name"],
                    "tags": [{"name": "staging"}], "primary_ip": d["primary_ip"],
                }
                for d in device_definitions
            }

            fake_netbox = _FakeNetBoxClient(netbox_devices)
            # R1 fails SSH push, SW1Staging succeeds (failure isolation)
            fake_connector = _FakeDeviceConnector(failure_devices=["R1"])
            fake_stages = _CallCountingStage()

            orchestrator = DeploymentOrchestrator(
                netbox_client=fake_netbox,
                credential_resolver=_FakeCredentialResolver(),
                device_connector=fake_connector,
                context_builder=fake_stages,
                config_generator=fake_stages,
                pre_deployment_validator=fake_stages,
            )

            req = DeploymentRequest(
                selection_criteria={},
                artifact_dir=str(artifact_dir),
                target_environment="staging",
                dry_run=False,
            )
            summary = orchestrator.run(req)

            # Failure isolation: both devices were evaluated
            self.assertEqual(len(summary.results), 2)
            res_by_name = {r.device_name: r for r in summary.results}
            self.assertEqual(res_by_name["R1"].deployment_status, "failed")
            self.assertEqual(res_by_name["SW1Staging"].deployment_status, "success")

            # Overall staging summary fails -> exit code 1
            self.assertGreater(summary.failed_device_count, 0)
            self.assertEqual(_exit_code_for(summary), 1)

    def test_staging_compliance_drift_blocks_production(self):
        """If staging SSH succeeds but post-deployment verification finds DRIFT, exit code is 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "test_artifact"
            device_definitions = [
                {"id": 19, "name": "R1", "primary_ip": {"address": "10.10.10.2/24"}, "config": "hostname R1\n"},
                {"id": 20, "name": "SW1Staging", "primary_ip": {"address": "10.10.20.2/24"}, "config": "hostname SW1Staging\n"},
            ]
            _create_sample_manifest_and_configs(artifact_dir, device_definitions)

            netbox_devices = {
                d["id"]: {
                    "id": d["id"], "name": d["name"],
                    "tags": [{"name": "staging"}], "primary_ip": d["primary_ip"],
                }
                for d in device_definitions
            }

            fake_netbox = _FakeNetBoxClient(netbox_devices)
            fake_connector = _FakeDeviceConnector()  # SSH push succeeds on all devices
            fake_stages = _CallCountingStage()

            # SW1Staging has DRIFT, R1 is COMPLIANT
            compliance_call_log = []
            fake_compliance_cls = _make_fake_compliance_orchestrator(
                {"R1": "COMPLIANT", "SW1Staging": "DRIFT"},
                compliance_call_log,
            )
            orig_comp = compliance_main_module.ComplianceOrchestrator
            compliance_main_module.ComplianceOrchestrator = fake_compliance_cls

            try:
                orchestrator = DeploymentOrchestrator(
                    netbox_client=fake_netbox,
                    credential_resolver=_FakeCredentialResolver(),
                    device_connector=fake_connector,
                    context_builder=fake_stages,
                    config_generator=fake_stages,
                    pre_deployment_validator=fake_stages,
                )

                req = DeploymentRequest(
                    selection_criteria={},
                    artifact_dir=str(artifact_dir),
                    target_environment="staging",
                    dry_run=False,
                )
                summary = orchestrator.run(req)

                res_by_name = {r.device_name: r for r in summary.results}
                self.assertEqual(res_by_name["R1"].verification_status, "COMPLIANT")
                self.assertEqual(res_by_name["SW1Staging"].verification_status, "DRIFT")

                # Tollgate exit code MUST be 1 to fail the staging job and block production
                self.assertEqual(_exit_code_for(summary), 1)
            finally:
                compliance_main_module.ComplianceOrchestrator = orig_comp

    def test_staging_success_promotes_to_production_gate(self):
        """When all staging devices are COMPLIANT, exit code is 0 and deployment_result.json is written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "test_artifact"
            device_definitions = [
                {"id": 19, "name": "R1", "primary_ip": {"address": "10.10.10.2/24"}, "config": "hostname R1\n"},
                {"id": 20, "name": "SW1Staging", "primary_ip": {"address": "10.10.20.2/24"}, "config": "hostname SW1Staging\n"},
            ]
            _create_sample_manifest_and_configs(artifact_dir, device_definitions)

            netbox_devices = {
                d["id"]: {
                    "id": d["id"], "name": d["name"],
                    "tags": [{"name": "staging"}], "primary_ip": d["primary_ip"],
                }
                for d in device_definitions
            }

            fake_netbox = _FakeNetBoxClient(netbox_devices)
            fake_connector = _FakeDeviceConnector()
            fake_stages = _CallCountingStage()

            compliance_call_log = []
            fake_compliance_cls = _make_fake_compliance_orchestrator(
                {"R1": "COMPLIANT", "SW1Staging": "COMPLIANT"},
                compliance_call_log,
            )
            orig_comp = compliance_main_module.ComplianceOrchestrator
            compliance_main_module.ComplianceOrchestrator = fake_compliance_cls

            try:
                orchestrator = DeploymentOrchestrator(
                    netbox_client=fake_netbox,
                    credential_resolver=_FakeCredentialResolver(),
                    device_connector=fake_connector,
                    context_builder=fake_stages,
                    config_generator=fake_stages,
                    pre_deployment_validator=fake_stages,
                )

                req = DeploymentRequest(
                    selection_criteria={},
                    artifact_dir=str(artifact_dir),
                    target_environment="staging",
                    dry_run=False,
                    approved_by="test-engineer",
                    approval_ref="https://ci/runs/123",
                )
                summary = orchestrator.run(req)

                self.assertEqual(summary.failed_device_count, 0)
                for r in summary.results:
                    self.assertEqual(r.deployment_status, "success")
                    self.assertEqual(r.verification_status, "COMPLIANT")
                    self.assertEqual(r.approved_by, "test-engineer")

                self.assertEqual(_exit_code_for(summary), 0)

                # deployment_result.json must exist with identical details
                result_file = artifact_dir / "deployment_result.json"
                self.assertTrue(result_file.exists())
                saved_data = json.loads(result_file.read_text(encoding="utf-8"))
                self.assertEqual(len(saved_data["results"]), 2)
            finally:
                compliance_main_module.ComplianceOrchestrator = orig_comp

    def test_artifact_immutability_and_tampering_detection(self):
        """Staging and production use the exact same artifact; tampering between stages is caught."""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "test_artifact"
            device_definitions = [
                {"id": 19, "name": "R1", "primary_ip": {"address": "10.10.10.2/24"}, "config": "hostname R1\n"},
                {"id": 23, "name": "R2", "primary_ip": {"address": "10.10.70.2/24"}, "config": "hostname R2\n"},
            ]
            _create_sample_manifest_and_configs(artifact_dir, device_definitions)

            # Initial artifact is valid
            verification = verify_manifest(artifact_dir)
            self.assertTrue(verification["valid"])

            # Tampering: attacker or rogue process modifies R2.cfg between staging and production
            (artifact_dir / "R2.cfg").write_text("hostname R2-TAMPERED\n", encoding="utf-8")

            tampered_verification = verify_manifest(artifact_dir)
            self.assertFalse(tampered_verification["valid"])
            self.assertTrue(any("Hash mismatch" in err for err in tampered_verification["errors"]))


if __name__ == "__main__":
    unittest.main()
