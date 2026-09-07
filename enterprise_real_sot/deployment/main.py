"""
Purpose   : Central orchestrator managing device selection, context building, CLI rendering, pre-deployment validation, and SSH push.
Called By : cli.py (`DeploymentOrchestrator.run()`).
Calls Next: device_selector.py -> context_builder.py -> config_generator.py -> pre_deployment_validation -> device_connector.py -> artifact_manager.py.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence


from deployment.config_generator import ConfigGenerator
from deployment.context_builder import ContextBuilder
from deployment.device_connector import DeploymentResult, DeviceConnector
from deployment.device_selector import DeviceSelector
from deployment.logger import get_logger
from deployment.netbox_client import NetBoxClient


from deployment.credentials import CredentialResolver
from deployment.lifecycle import BatchLifecycleState, DeviceLifecycleState
from pre_deployment_validation import PreDeploymentValidator, PreDeploymentValidationReport





logger = get_logger("DeploymentMain")


# Input request dataclass specifying device selection filters, SSH credential mappings, and protocol options.
@dataclass(frozen=True)
class DeploymentRequest:
    """Inputs required to orchestrate one deployment workflow."""

    selection_criteria: Mapping[str, Any]
    connection_details: Optional[Mapping[str, Mapping[str, Any]]] = None
    requested_protocols: Optional[Sequence[str]] = None
    requested_interfaces: Optional[Sequence[str]] = None
    excluded_interfaces: Optional[Sequence[str]] = None
    save_config: bool = False
    dry_run: bool = False
    # Phase 1 -- Exact Artifact Deployment. When set, `run()` never selects devices,
    # never rebuilds context, never regenerates configuration, and never validates:
    # it re-verifies the artifact at this path and deploys its exact recorded .cfg
    # files. All fields above (selection_criteria, requested_protocols, etc.) are
    # ignored in this mode -- the artifact's manifest.json is authoritative.
    artifact_dir: Optional[str] = None
    # Stage 0 CSV->NetBox Config Context sync is opt-in only (never implicit), and
    # is never performed at all in artifact_dir mode regardless of this flag.
    sync_sot: bool = False
    # Audit-only metadata (Phase 1 Step 7): never bypasses validation or manifest
    # verification, never itself grants deployment permission. Recorded verbatim
    # onto every DeploymentResult produced by this run.
    approved_by: Optional[str] = None
    approval_ref: Optional[str] = None


# Result dataclass capturing Pre-Deployment Assessment outcomes for a single target device.
@dataclass(frozen=True)
class AssessmentResult:
    """Outcome of Pre-Deployment Assessment for a target device."""

    device_name: str
    device: Optional[Mapping[str, Any]] = None
    device_context: Optional[Mapping[str, Any]] = None
    connection_details: Optional[Mapping[str, Any]] = None
    generated_configuration: Optional[str] = None
    validation_report: Optional[PreDeploymentValidationReport] = None
    is_candidate: bool = False
    failure_reason: Optional[str] = None
    state: str = DeviceLifecycleState.SELECTED.value
# Aggregated outcome summary dataclass reporting overall execution results across all target switches.
@dataclass(frozen=True)
class DeploymentSummary:
    """Aggregated result of a deployment request."""

    selected_device_count: int
    succeeded_device_count: int
    failed_device_count: int
    results: Sequence[DeploymentResult]
    assessment_results: Sequence[AssessmentResult] = ()
    assessment_passed_count: int = 0
    assessment_failed_count: int = 0
    skipped_device_count: int = 0
    artifact_dir: Optional[str] = None
    error_message: Optional[str] = None




    @property
    def batch_size(self) -> int:
        return self.selected_device_count

    @property
    def assessment_successful_count(self) -> int:
        return self.assessment_passed_count

    @property
    def assessment_unsuccessful_count(self) -> int:
        return self.assessment_failed_count

    @property
    def deployment_candidates_count(self) -> int:
        return self.assessment_passed_count

    @property
    def devices_deployed_count(self) -> int:
        return self.succeeded_device_count

    @property
    def deployment_failed_count(self) -> int:
        return self.failed_device_count

    @property
    def devices_skipped_count(self) -> int:
        return self.skipped_device_count


class DeploymentOrchestrator:
    """Coordinate selection, context, generation, and device deployment.

    Each collaborator owns its own business responsibility. This class only
    passes outputs to the next stage and aggregates structured results.
    """

    def __init__(
        self,
        netbox_client: Optional[NetBoxClient] = None,
        device_selector: Optional[DeviceSelector] = None,
        context_builder: Optional[ContextBuilder] = None,
        config_generator: Optional[ConfigGenerator] = None,
        device_connector: Optional[DeviceConnector] = None,
        credential_resolver: Optional[CredentialResolver] = None,
        pre_deployment_validator: Optional[PreDeploymentValidator] = None,
    ) -> None:
        # Dependency injection pattern: Instantiates default stage collaborators if none are provided.
        # This allows injecting mock objects during unit testing to test each pipeline stage independently.
        self.netbox_client = netbox_client or NetBoxClient()
        self.device_selector = device_selector or DeviceSelector(self.netbox_client)
        self.context_builder = context_builder or ContextBuilder(self.netbox_client)
        self.config_generator = config_generator or ConfigGenerator()
        self.device_connector = device_connector or DeviceConnector()
        self.credential_resolver = credential_resolver or CredentialResolver()
        self.pre_deployment_validator = pre_deployment_validator or PreDeploymentValidator()

    def run(self, deployment_request: DeploymentRequest) -> DeploymentSummary:
        """Run the deployment workflow and return its aggregated outcome."""
        # Validate selection criteria and connection details payload format before initiating network operations.
        request_error = self._validate_request(deployment_request)
        if request_error:
            return self._failed_summary(request_error)

        if deployment_request.artifact_dir:
            # Phase 1 -- Exact Artifact Deployment. Entirely separate path: never
            # selects devices, never syncs SoT, never rebuilds context, never
            # regenerates configuration, never re-validates. See _run_from_artifact.
            summary = self._run_from_artifact(deployment_request)
            return self._apply_approval_metadata(summary, deployment_request)

        logger.info("Deployment started.")
        # Stage 0: Automated NetBox SoT Sync (synchronize CSV config context into NetBox REST API).
        # Opt-in only via --sync-sot -- never runs implicitly.
        if deployment_request.sync_sot:
            try:
                import os, sys
                importers_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../python/importers"))
                if importers_dir not in sys.path:
                    sys.path.insert(0, importers_dir)
                from import_config_context import run_config_context_import
                logger.info("Synchronizing CSV Config Context intent into NetBox REST API (--sync-sot)...")
                run_config_context_import()
            except Exception as sync_err:
                logger.warning("Automated Config Context pre-sync warning: %s", sync_err)


        try:
            # Stage 1: Query NetBox to select target network devices matching specified filter criteria.
            selected_devices = self.device_selector.select_devices(
                dict(deployment_request.selection_criteria)
            )

        except Exception as error:
            message = f"Device selection failed: {error}"
            logger.error(message)
            return self._failed_summary(message)

        logger.info("Selected %d device(s) for deployment batch.", len(selected_devices))

        # =========================================================================
        # PHASE 1: PRE-DEPLOYMENT ASSESSMENT (ALL DEVICES IN BATCH)
        # =========================================================================
        logger.info("=== PHASE 1: PRE-DEPLOYMENT ASSESSMENT ===")
        assessment_results: List[AssessmentResult] = []
        deployment_candidates: List[AssessmentResult] = []
        skipped_assessments: List[AssessmentResult] = []

        for device in selected_devices:
            assessment = self._assess_device(device, deployment_request)
            assessment_results.append(assessment)
            if assessment.is_candidate:
                deployment_candidates.append(assessment)
            else:
                skipped_assessments.append(assessment)

        assessment_passed_count = len(deployment_candidates)
        assessment_failed_count = len(skipped_assessments)

        logger.info(
            "Pre-Deployment Assessment complete: Total=%d, Deployment Candidates=%d, Skipped Devices=%d.",
            len(selected_devices),
            assessment_passed_count,
            assessment_failed_count,
        )

        # Create artifact directory, save .cfg files for Candidates, and generate summary.txt
        artifact_dir_str = None
        if selected_devices:
            from datetime import datetime
            from deployment.artifact_manager import (
                create_pre_deployment_dir,
                generate_batch_name,
                write_manifest,
                write_summary_report,
            )

            now = datetime.now()
            artifact_dir = create_pre_deployment_dir(
                selection_criteria=deployment_request.selection_criteria,
                devices=selected_devices,
                timestamp=now,
            )
            artifact_dir_str = str(artifact_dir)
            batch_name = generate_batch_name(
                selection_criteria=deployment_request.selection_criteria,
                devices=selected_devices,
            )
            logger.info("Pre-deployment artifact directory created: %s", artifact_dir_str)

            # 1. Save candidate .cfg files (Skipped devices generate NO .cfg files)
            for candidate in deployment_candidates:
                cfg_file_path = artifact_dir / f"{candidate.device_name}.cfg"
                cfg_content = candidate.generated_configuration or ""
                with open(cfg_file_path, "w", encoding="utf-8") as f:
                    f.write(cfg_content)
                logger.info(
                    "Saved generated CLI artifact for candidate device '%s' -> %s",
                    candidate.device_name,
                    cfg_file_path,
                )

            # 2. Write summary.txt inside artifact folder
            summary_txt_path = write_summary_report(
                artifact_dir=artifact_dir,
                timestamp_str=now.strftime("%Y-%m-%d %H:%M:%S"),
                batch_name=batch_name,
                total_devices=len(selected_devices),
                assessment_passed=assessment_passed_count,
                assessment_failed=assessment_failed_count,
                deployment_candidates_count=assessment_passed_count,
                skipped_devices_count=assessment_failed_count,
                assessment_results=assessment_results,
            )
            logger.info("Saved batch summary report -> %s", summary_txt_path)

            # 3. Write manifest.json -- the immutable deployment contract for this artifact.
            #    Only deployment_candidates (passed Pre-Deployment Validation) are eligible;
            #    skipped_assessments are recorded for audit only, never as deployable.
            manifest_path = write_manifest(
                artifact_dir=artifact_dir,
                batch_id=artifact_dir.name,
                timestamp=now,
                candidates=deployment_candidates,
                skipped=skipped_assessments,
            )
            logger.info("Saved deployment manifest -> %s", manifest_path)

        # =========================================================================
        # PHASE 2: SELECTIVE DEPLOYMENT (DEPLOYMENT CANDIDATES ONLY)
        # =========================================================================
        logger.info("=== PHASE 2: SELECTIVE DEPLOYMENT ===")
        deployment_results: List[DeploymentResult] = []

        # Record non-connected deployment results for skipped devices
        for skipped in skipped_assessments:
            ip_address = self._target_address(skipped.connection_details) if skipped.connection_details else None
            deployment_results.append(
                self._failed_result(
                    device_name=skipped.device_name,
                    ip_address=ip_address,
                    error_message=skipped.failure_reason or "Pre-deployment assessment failed",
                )
            )

        # Execute SSH deployment (or dry-run) for candidates
        for candidate in deployment_candidates:
            deployment_results.append(
                self._deploy_candidate(candidate, deployment_request)
            )

        # =========================================================================
        # PHASE 3: POST-DEPLOYMENT COMPLIANCE VALIDATION (REUSING ComplianceOrchestrator)
        # =========================================================================
        if not deployment_request.dry_run:
            try:
                from post_deployment_validation.main import ComplianceOrchestrator, ComplianceRequest
                logger.info("=== PHASE 3: POST-DEPLOYMENT COMPLIANCE VALIDATION ===")
                compliance_orchestrator = ComplianceOrchestrator(netbox_client=self.netbox_client)
                comp_req = ComplianceRequest(
                    selection_criteria=deployment_request.selection_criteria,
                    connection_details=deployment_request.connection_details,
                    requested_protocols=deployment_request.requested_protocols,
                    requested_interfaces=deployment_request.requested_interfaces,
                )
                compliance_summary = compliance_orchestrator.run(comp_req)
                logger.info(
                    "Post-Deployment Compliance Validation complete: Compliant=%d, Drifted=%d, Unreachable=%d, Failed=%d.",
                    compliance_summary.compliant_device_count,
                    compliance_summary.drifted_device_count,
                    compliance_summary.unreachable_device_count,
                    compliance_summary.failed_device_count,
                )
                # Map ComplianceOrchestrator outcomes to DeviceLifecycleState. This is the
                # ONLY place deployment/main.py touches the post_deployment_validation
                # verdict -- it reads `overall_status` verbatim and never re-derives it.
                comp_map = {res.device_name: res.overall_status for res in compliance_summary.results}
                updated_results = []
                for res in deployment_results:
                    if res.device_name in comp_map and res.deployment_status == "success":
                        st = comp_map[res.device_name]
                        # `state` may stay a coarse deployment lifecycle stage (verified vs.
                        # not), but `verification_status` below carries the EXACT verdict
                        # string from post_deployment_validation (COMPLIANT/DRIFT/
                        # UNREACHABLE/FAILED) -- never collapsed into a SUCCESS/FAILED pair.
                        final_state = DeviceLifecycleState.DEPLOYED_AND_VERIFIED.value if st == "COMPLIANT" else DeviceLifecycleState.DEPLOYED_VERIFICATION_FAILED.value
                        ver_stat = st
                        updated_results.append(
                            DeploymentResult(
                                device_name=res.device_name,
                                ip_address=res.ip_address,
                                connection_status=res.connection_status,
                                deployment_status=res.deployment_status,
                                commands_sent=res.commands_sent,
                                execution_time_seconds=res.execution_time_seconds,
                                error_message=res.error_message,
                                state=final_state if res.state != DeviceLifecycleState.ALREADY_COMPLIANT.value else res.state,
                                desired_items_count=res.desired_items_count,
                                compliant_items_count=res.compliant_items_count,
                                change_required_count=res.change_required_count,
                                backup_saved=res.backup_saved,
                                rollback_status=res.rollback_status,
                                verification_status=ver_stat,
                            )
                        )
                    else:
                        updated_results.append(res)
                deployment_results = updated_results
            except Exception as comp_err:
                logger.warning("Post-deployment ComplianceOrchestrator execution warning: %s", comp_err)

        # =========================================================================
        # PHASE 4: BATCH SUMMARY REPORTING
        # =========================================================================
        summary = self._build_summary(
            selected_device_count=len(selected_devices),
            assessment_passed_count=assessment_passed_count,
            assessment_failed_count=assessment_failed_count,
            skipped_device_count=len(skipped_assessments),
            assessment_results=assessment_results,
            results=deployment_results,
            artifact_dir=artifact_dir_str,
        )
        self._log_summary(summary)
        return self._apply_approval_metadata(summary, deployment_request)

    def _run_from_artifact(self, deployment_request: DeploymentRequest) -> DeploymentSummary:
        """Phase 1 -- Exact Artifact Deployment.

        Deploys the EXACT configuration already validated and sealed into
        `deployment_request.artifact_dir`'s manifest.json (Phase 0). This method
        never calls self.context_builder, self.config_generator, or
        self.pre_deployment_validator -- the artifact's manifest is the
        authoritative record that those stages already ran and passed, and
        VALIDATED CONFIG == APPROVED CONFIG == DEPLOYED CONFIG requires that no
        regeneration opportunity exists between artifact creation and deployment.

        Flow: verify_manifest() -> reject immediately on any failure (missing
        manifest, tampered/missing config, bad batch_hash, deployable=false) ->
        re-query NetBox by device_id for each manifest device -> verify identity
        (id + name match) -> load the exact recorded .cfg -> hand it to the
        existing _deploy_candidate()/DeviceConnector path unchanged.
        """
        from deployment.artifact_manager import verify_manifest

        artifact_dir = Path(deployment_request.artifact_dir)
        logger.info("=== ARTIFACT DEPLOYMENT MODE (Phase 1): %s ===", artifact_dir)

        verification = verify_manifest(artifact_dir)
        if not verification["valid"]:
            message = "Artifact verification failed: " + "; ".join(verification["errors"])
            logger.error(message)
            return self._failed_summary(message)

        manifest = verification["manifest"]
        manifest_devices = manifest.get("devices", [])
        logger.info(
            "Artifact verified OK. batch_id=%s git_commit_sha=%s deployable_devices=%d",
            manifest.get("batch_id"),
            manifest.get("git_commit_sha"),
            len(manifest_devices),
        )

        # Re-verify device identity against live NetBox for every manifest device.
        # NEVER re-select devices by site/role/name -- the manifest defines the
        # exact batch; a failed identity check STOPs deployment for that device
        # only, and must never fall back to selecting a similarly-named device.
        assessment_results: List[AssessmentResult] = []
        deployment_candidates: List[AssessmentResult] = []
        identity_failures: List[AssessmentResult] = []

        for manifest_device in manifest_devices:
            assessment = self._build_candidate_from_artifact(manifest_device, artifact_dir)
            assessment_results.append(assessment)
            if assessment.is_candidate:
                deployment_candidates.append(assessment)
            else:
                identity_failures.append(assessment)

        logger.info(
            "Device identity re-verification complete: Total=%d, Verified=%d, Failed=%d.",
            len(assessment_results),
            len(deployment_candidates),
            len(identity_failures),
        )

        deployment_results: List[DeploymentResult] = []
        for failure in identity_failures:
            ip_address = self._target_address(failure.connection_details) if failure.connection_details else None
            deployment_results.append(
                self._failed_result(
                    device_name=failure.device_name,
                    ip_address=ip_address,
                    error_message=failure.failure_reason or "Device identity verification failed",
                    state=DeviceLifecycleState.VALIDATION_FAILED.value,
                )
            )

        # Reuse the existing deploy path unchanged (handles dry_run vs. live SSH,
        # backup, selective push, rollback, save-config -- none of that changes).
        for candidate in deployment_candidates:
            deployment_results.append(self._deploy_candidate(candidate, deployment_request))

        summary = self._build_summary(
            selected_device_count=len(assessment_results),
            assessment_passed_count=len(deployment_candidates),
            assessment_failed_count=len(identity_failures),
            skipped_device_count=len(identity_failures),
            assessment_results=assessment_results,
            results=deployment_results,
            artifact_dir=str(artifact_dir),
        )
        self._log_summary(summary)
        return summary

    def _build_candidate_from_artifact(
        self,
        manifest_device: Mapping[str, Any],
        artifact_dir: Path,
    ) -> AssessmentResult:
        """Re-verify one manifest device's identity against live NetBox, then load
        its EXACT recorded .cfg (never regenerated). Connection details are
        resolved from the freshly re-queried NetBox record -- the manifest itself
        carries no credentials -- via the same CredentialResolver normal
        deployment uses, so IP/platform changes since artifact creation are
        picked up honestly rather than trusted from stale artifact metadata.
        """
        device_id = manifest_device.get("device_id")
        device_name = manifest_device.get("device_name") or "unknown"
        config_file = manifest_device.get("config_file")

        if device_id is None:
            message = f"DEVICE_IDENTITY_MISMATCH: manifest entry for '{device_name}' has no device_id."
            logger.error(message)
            return AssessmentResult(
                device_name=device_name,
                is_candidate=False,
                failure_reason=message,
                state=DeviceLifecycleState.VALIDATION_FAILED.value,
            )

        try:
            fresh_device = self.netbox_client.get(f"dcim/devices/{device_id}/")
        except Exception as error:
            message = f"DEVICE_IDENTITY_MISMATCH: NetBox lookup failed for device_id={device_id} ('{device_name}'): {error}"
            logger.error(message)
            return AssessmentResult(
                device_name=device_name,
                is_candidate=False,
                failure_reason=message,
                state=DeviceLifecycleState.VALIDATION_FAILED.value,
            )

        if not isinstance(fresh_device, Mapping) or fresh_device.get("id") != device_id:
            actual_id = fresh_device.get("id") if isinstance(fresh_device, Mapping) else None
            message = (
                f"DEVICE_IDENTITY_MISMATCH: manifest device_id={device_id} ('{device_name}') did not resolve "
                f"to a matching NetBox device id (got id={actual_id!r})."
            )
            logger.error(message)
            return AssessmentResult(
                device_name=device_name,
                is_candidate=False,
                failure_reason=message,
                state=DeviceLifecycleState.VALIDATION_FAILED.value,
            )

        if fresh_device.get("name") != device_name:
            message = (
                f"DEVICE_IDENTITY_MISMATCH: NetBox device_id={device_id} now has name "
                f"'{fresh_device.get('name')}', but manifest recorded '{device_name}'."
            )
            logger.error(message)
            return AssessmentResult(
                device_name=device_name,
                device=fresh_device,
                is_candidate=False,
                failure_reason=message,
                state=DeviceLifecycleState.VALIDATION_FAILED.value,
            )

        # Staleness signal only (never a hard block) -- NetBox's `last_updated` is
        # not consistently surfaced by every code path today, so a missing value
        # on either side is not itself an error.
        manifest_last_updated = manifest_device.get("device_last_updated")
        fresh_last_updated = fresh_device.get("last_updated")
        if manifest_last_updated and fresh_last_updated and manifest_last_updated != fresh_last_updated:
            logger.warning(
                "Staleness signal for device '%s' (device_id=%s): manifest device_last_updated=%s, "
                "current NetBox last_updated=%s. Deploying the exact artifact config regardless -- "
                "NetBox metadata has changed since the artifact was created.",
                device_name,
                device_id,
                manifest_last_updated,
                fresh_last_updated,
            )

        config_path = Path(artifact_dir) / config_file if config_file else None
        if not config_path or not config_path.exists():
            message = f"Artifact config file missing at deployment time for '{device_name}': {config_file}"
            logger.error(message)
            return AssessmentResult(
                device_name=device_name,
                device=fresh_device,
                is_candidate=False,
                failure_reason=message,
                state=DeviceLifecycleState.VALIDATION_FAILED.value,
            )

        exact_configuration = config_path.read_text(encoding="utf-8")

        try:
            connection_details = self.credential_resolver.resolve_connection_details(fresh_device)
        except Exception as error:
            message = f"Credential resolution failed: {error}"
            logger.error("%s Device: '%s'.", message, device_name)
            return AssessmentResult(
                device_name=device_name,
                device=fresh_device,
                is_candidate=False,
                failure_reason=message,
                state=DeviceLifecycleState.VALIDATION_FAILED.value,
            )

        logger.info(
            "Device identity verified for '%s' (device_id=%s). Loaded EXACT artifact config '%s' "
            "(config_sha256=%s) -- no regeneration performed.",
            device_name,
            device_id,
            config_file,
            manifest_device.get("config_sha256"),
        )

        return AssessmentResult(
            device_name=device_name,
            device=fresh_device,
            connection_details=connection_details,
            generated_configuration=exact_configuration,
            is_candidate=True,
            state=DeviceLifecycleState.VALIDATED.value,
        )

    @staticmethod
    def _apply_approval_metadata(
        summary: DeploymentSummary,
        deployment_request: DeploymentRequest,
    ) -> DeploymentSummary:
        """Stamp --approved-by / --approval-ref audit metadata onto every
        DeploymentResult using the existing reporting structures. Pure audit
        evidence: never influences validation, manifest verification, or
        whether any device was deployed -- it only records who/what triggered
        this run for later audit review.
        """
        if deployment_request.approved_by is None and deployment_request.approval_ref is None:
            return summary

        import dataclasses

        stamped_results = tuple(
            dataclasses.replace(
                result,
                approved_by=deployment_request.approved_by,
                approval_ref=deployment_request.approval_ref,
            )
            for result in summary.results
        )
        return dataclasses.replace(summary, results=stamped_results)

    def _assess_device(
        self,
        device: Mapping[str, Any],
        deployment_request: DeploymentRequest,
    ) -> AssessmentResult:
        """Phase 1: Perform Context Building, Config Generation, and Pre-Deployment Validation for one device."""
        device_name = device.get("name")
        if not isinstance(device_name, str) or not device_name:
            return AssessmentResult(
                device_name="",
                device=device if isinstance(device, Mapping) else None,
                is_candidate=False,
                failure_reason="Selected device is missing a valid name.",
                state=DeviceLifecycleState.VALIDATION_FAILED.value,
            )

        connection_details = None
        if isinstance(deployment_request.connection_details, Mapping):
            connection_details = deployment_request.connection_details.get(device_name)

        if not connection_details:
            try:
                connection_details = self.credential_resolver.resolve_connection_details(device)
            except Exception as error:
                message = f"Credential resolution failed: {error}"
                logger.error("%s Device: '%s'.", message, device_name)
                return AssessmentResult(
                    device_name=device_name,
                    device=device,
                    is_candidate=False,
                    failure_reason=message,
                    state=DeviceLifecycleState.VALIDATION_FAILED.value,
                )

        try:
            logger.info("Building deployment context for device '%s'.", device_name)
            device_context = self.context_builder.build_device_context(dict(device))

            logger.info("Generating configuration for device '%s'.", device_name)
            generated_configuration = self.config_generator.generate(
                device_context,
                deployment_request.requested_protocols,
                deployment_request.requested_interfaces,
                deployment_request.excluded_interfaces,
            )

            logger.info("Executing pre-deployment validation for device '%s'.", device_name)
            validation_report = self.pre_deployment_validator.validate(
                device=device,
                device_context=device_context,
                generated_configuration=generated_configuration,
                requested_protocols=deployment_request.requested_protocols,
                requested_interfaces=deployment_request.requested_interfaces,
            )

            site = str(device.get("site", {}).get("slug", "hyderabad")) if isinstance(device.get("site"), dict) else "hyderabad"
            role = str(device.get("device_role", {}).get("slug", "access")) if isinstance(device.get("device_role"), dict) else "access"

            if not validation_report.is_valid:
                error_msg = f"Pre-deployment validation failed: {'; '.join(validation_report.error_messages)}"
                logger.error("%s Device: '%s'.", error_msg, device_name)
                return AssessmentResult(
                    device_name=device_name,
                    device=device,
                    device_context=device_context,
                    connection_details=connection_details,
                    generated_configuration=generated_configuration,
                    validation_report=validation_report,
                    is_candidate=False,
                    failure_reason=error_msg,
                    state=DeviceLifecycleState.VALIDATION_FAILED.value,
                )

            # Calculate generated command count
            cmd_lines = [
                c.strip() for c in generated_configuration.splitlines()
                if c.strip() and not c.strip().startswith("!")
            ]
            logger.info(
                "Pre-deployment validation PASSED for device '%s'. Generated CLI configuration (%d commands) is approved for deployment.",
                device_name,
                len(cmd_lines),
            )

            # Pre-Deployment Assessment passed: Mark as Deployment Candidate with VALIDATED state
            return AssessmentResult(
                device_name=device_name,
                device=device,
                device_context=device_context,
                connection_details=connection_details,
                generated_configuration=generated_configuration,
                validation_report=validation_report,
                is_candidate=True,
                state=DeviceLifecycleState.VALIDATED.value,
            )

        except Exception as error:
            message = f"Pre-deployment assessment failed: {error}"
            logger.error("%s Device: '%s'.", message, device_name)
            return AssessmentResult(
                device_name=device_name,
                device=device,
                connection_details=connection_details,
                is_candidate=False,
                failure_reason=message,
                state=DeviceLifecycleState.VALIDATION_FAILED.value,
            )

    def _deploy_candidate(
        self,
        candidate: AssessmentResult,
        deployment_request: DeploymentRequest,
    ) -> DeploymentResult:
        """Phase 2: Deploy an assessed Deployment Candidate over SSH (or perform dry-run)."""
        device_name = candidate.device_name
        connection_details = candidate.connection_details or {}
        generated_configuration = candidate.generated_configuration or ""
        cmd_lines = [
            c.strip() for c in generated_configuration.splitlines()
            if c.strip() and not c.strip().startswith("!")
        ]

        if deployment_request.dry_run:
            logger.info("Dry-run requested for device '%s'. Skipping SSH deployment.", device_name)
            return DeploymentResult(
                device_name=device_name,
                ip_address=self._target_address(connection_details),
                connection_status="dry_run",
                deployment_status="success",
                commands_sent=0,
                execution_time_seconds=0.0,
                error_message=generated_configuration,
                state=DeviceLifecycleState.DRY_RUN.value,
            )

        logger.info(
            "Deploying approved configuration (%d commands) to device '%s' at '%s'. State: DEPLOYING.",
            len(cmd_lines),
            device_name,
            self._target_address(connection_details),
        )
        site = "hyderabad"
        role = "access" if "SW" in device_name else "router"
        import time
        start_time = time.time()
        try:
            raw_result = self.device_connector.deploy(
                device_name=device_name,
                connection_details=connection_details,
                generated_configuration=generated_configuration,
                save_config=deployment_request.save_config,
            )
            elapsed_time = time.time() - start_time
            final_state = (
                raw_result.state
                if raw_result.state
                else (
                    DeviceLifecycleState.DEPLOYED.value
                    if raw_result.deployment_status == "success"
                    else DeviceLifecycleState.DEPLOYMENT_FAILED.value
                )
            )

            return DeploymentResult(
                device_name=raw_result.device_name,
                ip_address=raw_result.ip_address,
                connection_status=raw_result.connection_status,
                deployment_status=raw_result.deployment_status,
                commands_sent=raw_result.commands_sent,
                execution_time_seconds=raw_result.execution_time_seconds,
                error_message=raw_result.error_message,
                state=final_state,
                desired_items_count=getattr(raw_result, "desired_items_count", 0),
                compliant_items_count=getattr(raw_result, "compliant_items_count", 0),
                change_required_count=getattr(raw_result, "change_required_count", 0),
                backup_saved=getattr(raw_result, "backup_saved", False),
                rollback_status=getattr(raw_result, "rollback_status", "NOT_REQUIRED"),
                verification_status=getattr(raw_result, "verification_status", "SKIPPED"),
            )

        except Exception as error:
            message = f"Deployment execution failed: {error}"
            logger.error("%s Device: '%s'.", message, device_name)
            return self._failed_result(
                device_name,
                self._target_address(connection_details),
                message,
                state=DeviceLifecycleState.DEPLOYMENT_FAILED.value,
            )

    @staticmethod
    def _validate_request(deployment_request: DeploymentRequest) -> Optional[str]:
        """Return an error for an invalid orchestration request, if present."""
        if not isinstance(deployment_request.selection_criteria, Mapping):
            return "Deployment request selection criteria must be a mapping."
        if (
            deployment_request.connection_details is not None
            and not isinstance(deployment_request.connection_details, Mapping)
        ):
            return "Deployment request connection details must be a mapping when provided."
        if (
            deployment_request.requested_protocols is not None
            and (
                not isinstance(deployment_request.requested_protocols, Sequence)
                or isinstance(deployment_request.requested_protocols, str)
            )
        ):
            return "Requested protocols must be a sequence when provided."
        if (
            deployment_request.requested_interfaces is not None
            and (
                not isinstance(deployment_request.requested_interfaces, Sequence)
                or isinstance(deployment_request.requested_interfaces, str)
            )
        ):
            return "Requested interfaces must be a sequence when provided."
        return None

    @staticmethod
    def _failed_result(
        device_name: str,
        ip_address: Optional[str],
        error_message: str,
        state: str = DeviceLifecycleState.VALIDATION_FAILED.value,
    ) -> DeploymentResult:
        """Create a structured failure before a connector result is available."""
        return DeploymentResult(
            device_name=device_name,
            ip_address=ip_address,
            connection_status="not_connected",
            deployment_status="failed",
            commands_sent=0,
            execution_time_seconds=0.0,
            error_message=error_message,
            state=state,
        )


    @staticmethod
    def _target_address(connection_details: Mapping[str, Any]) -> Optional[str]:
        """Return the configured transport target for failure reporting."""
        host = connection_details.get("host")
        return str(host) if host is not None else None

    @staticmethod
    def _build_summary(
        selected_device_count: int,
        results: Sequence[DeploymentResult],
        assessment_passed_count: int = 0,
        assessment_failed_count: int = 0,
        skipped_device_count: int = 0,
        assessment_results: Sequence[AssessmentResult] = (),
        artifact_dir: Optional[str] = None,
    ) -> DeploymentSummary:
        """Aggregate device results without changing their execution outcomes."""
        succeeded_device_count = sum(
            result.deployment_status == "success" for result in results
        )
        return DeploymentSummary(
            selected_device_count=selected_device_count,
            succeeded_device_count=succeeded_device_count,
            failed_device_count=len(results) - succeeded_device_count,
            results=tuple(results),
            assessment_results=tuple(assessment_results),
            assessment_passed_count=assessment_passed_count,
            assessment_failed_count=assessment_failed_count,
            skipped_device_count=skipped_device_count,
            artifact_dir=artifact_dir,
        )

    @staticmethod
    def _failed_summary(error_message: str) -> DeploymentSummary:
        """Return a clean workflow-level failure without raising to the caller."""
        logger.error("Deployment failed: %s", error_message)
        return DeploymentSummary(
            selected_device_count=0,
            succeeded_device_count=0,
            failed_device_count=0,
            results=(),
            error_message=error_message,
        )

    @staticmethod
    def _log_summary(summary: DeploymentSummary) -> None:
        """Log the concise deployment summary for the calling application."""
        logger.info(
            "Deployment Summary: Batch Size=%d | Assessment Successful=%d | Assessment Unsuccessful=%d | Candidates=%d | Deployed=%d | Skipped=%d | Failed=%d",
            summary.batch_size,
            summary.assessment_successful_count,
            summary.assessment_unsuccessful_count,
            summary.deployment_candidates_count,
            summary.devices_deployed_count,
            summary.devices_skipped_count,
            summary.deployment_failed_count,
        )


def main(
    deployment_request: DeploymentRequest,
    orchestrator: Optional[DeploymentOrchestrator] = None,
) -> DeploymentSummary:
    """Execute one deployment request through the Deployment Layer workflow."""
    active_orchestrator = orchestrator or DeploymentOrchestrator()
    return active_orchestrator.run(deployment_request)

