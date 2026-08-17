"""
Purpose   : Central orchestrator managing device selection, context building, CLI rendering, pre-deployment validation, and SSH push.
Called By : cli.py (`DeploymentOrchestrator.run()`).
Calls Next: device_selector.py -> context_builder.py -> config_generator.py -> pre_deployment_validation -> device_connector.py -> artifact_manager.py.
"""

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence


from deployment.config_generator import ConfigGenerator
from deployment.context_builder import ContextBuilder
from deployment.device_connector import DeploymentResult, DeviceConnector
from deployment.device_selector import DeviceSelector
from deployment.logger import get_logger
from deployment.netbox_client import NetBoxClient


from deployment.credentials import CredentialResolver
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

        logger.info("Deployment started.")
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
        # PHASE 3: BATCH SUMMARY REPORTING
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
        return summary

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

            # Pre-Deployment Assessment passed: Mark as Deployment Candidate
            return AssessmentResult(
                device_name=device_name,
                device=device,
                device_context=device_context,
                connection_details=connection_details,
                generated_configuration=generated_configuration,
                validation_report=validation_report,
                is_candidate=True,
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
            )

        logger.info(
            "Deploying approved configuration (%d commands) to device '%s' at '%s'.",
            len(cmd_lines),
            device_name,
            self._target_address(connection_details),
        )
        try:
            return self.device_connector.deploy(
                device_name=device_name,
                connection_details=connection_details,
                generated_configuration=generated_configuration,
                save_config=deployment_request.save_config,
            )
        except Exception as error:
            message = f"Deployment execution failed: {error}"
            logger.error("%s Device: '%s'.", message, device_name)
            return self._failed_result(
                device_name,
                self._target_address(connection_details),
                message,
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

