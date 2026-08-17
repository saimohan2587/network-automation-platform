"""Main orchestrator for pre-deployment validation stage."""

import logging
import time
from typing import Any, List, Mapping, Optional, Sequence

from pre_deployment_validation.registry import ValidatorRegistry
from pre_deployment_validation.report import (
    RULE_TYPE_TECHNICAL,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    PreDeploymentValidationReport,
    ValidationCheckResult,
)

logger = logging.getLogger("PreDeploymentValidator")


class PreDeploymentValidator:
    """Orchestrates in-memory pre-deployment validation checks across generic and protocol layers."""

    def __init__(self, registry: Optional[ValidatorRegistry] = None) -> None:
        self.registry = registry or ValidatorRegistry()

    def validate(
        self,
        device: Mapping[str, Any],
        device_context: Mapping[str, Any],
        generated_configuration: str,
        requested_protocols: Optional[Sequence[str]] = None,
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> PreDeploymentValidationReport:
        """Run pre-deployment validation checks and return an aggregated outcome report."""
        start_time = time.perf_counter()
        device_name = str(device.get("name", "Unknown-Device"))
        logger.info("Starting pre-deployment validation for device '%s'.", device_name)

        check_results: List[ValidationCheckResult] = []
        executed_validator_names: List[str] = ["GenericValidator"]

        # Step 1: Run generic system-wide validation checks
        generic_results = self._run_generic_validation(
            device=device,
            device_context=device_context,
            generated_configuration=generated_configuration,
            requested_interfaces=requested_interfaces,
        )
        check_results.extend(generic_results)

        # Step 2: Query registry for applicable protocol validator plugins
        applicable_validators = self.registry.get_applicable_validators(
            device_context=device_context,
            requested_protocols=requested_protocols,
        )

        # Step 3: Run each applicable protocol validator in priority order
        for validator in applicable_validators:
            executed_validator_names.append(validator.validator_name)
            try:
                protocol_results = validator.validate(
                    device=device,
                    device_context=device_context,
                    generated_configuration=generated_configuration,
                    requested_protocols=requested_protocols,
                    requested_interfaces=requested_interfaces,
                )
                check_results.extend(protocol_results)
            except Exception as error:
                logger.error(
                    "Validator '%s' encountered execution exception on device '%s': %s",
                    validator.validator_name,
                    device_name,
                    error,
                )
                check_results.append(
                    ValidationCheckResult(
                        check_name=f"{validator.validator_name}_execution",
                        passed=False,
                        severity=SEVERITY_ERROR,
                        rule_type=RULE_TYPE_TECHNICAL,
                        message=f"Validator exception: {error}",
                    )
                )

        execution_time_ms = (time.perf_counter() - start_time) * 1000.0

        # Step 4: Aggregate check results and evaluate overall report status
        total_checks = len(check_results)
        passed_checks = sum(1 for c in check_results if c.passed)
        failed_checks = sum(1 for c in check_results if not c.passed)

        # A report fails ONLY if a TECHNICAL ERROR severity check fails
        error_messages = [
            c.message
            for c in check_results
            if not c.passed and c.severity == SEVERITY_ERROR
        ]
        is_valid = len(error_messages) == 0

        logger.info(
            "Completed pre-deployment validation for '%s' in %.2fms. Valid: %s (%d/%d checks passed).",
            device_name,
            execution_time_ms,
            is_valid,
            passed_checks,
            total_checks,
        )

        return PreDeploymentValidationReport(
            device_name=device_name,
            is_valid=is_valid,
            total_checks=total_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            error_messages=error_messages,
            check_results=check_results,
            validator_names=executed_validator_names,
            execution_time_ms=execution_time_ms,
        )

    def _run_generic_validation(
        self,
        device: Mapping[str, Any],
        device_context: Mapping[str, Any],
        generated_configuration: str,
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> List[ValidationCheckResult]:
        """Execute generic structural and context validation checks."""
        results: List[ValidationCheckResult] = []

        # Check 1: Generated CLI is not empty
        if not generated_configuration or not generated_configuration.strip():
            results.append(
                ValidationCheckResult(
                    check_name="generic_cli_not_empty",
                    passed=False,
                    severity=SEVERITY_ERROR,
                    rule_type=RULE_TYPE_TECHNICAL,
                    message="Generated CLI configuration is empty or contains only whitespace.",
                )
            )
        else:
            results.append(
                ValidationCheckResult(
                    check_name="generic_cli_not_empty",
                    passed=True,
                    severity=SEVERITY_INFO,
                    rule_type=RULE_TYPE_TECHNICAL,
                    message="Generated CLI configuration is non-empty.",
                )
            )

        # Check 2: Device identity presence
        device_name = device.get("name") if isinstance(device, Mapping) else None
        if not device_name:
            results.append(
                ValidationCheckResult(
                    check_name="generic_device_name_present",
                    passed=False,
                    severity=SEVERITY_ERROR,
                    rule_type=RULE_TYPE_TECHNICAL,
                    message="Device dictionary missing required name attribute.",
                )
            )
        else:
            results.append(
                ValidationCheckResult(
                    check_name="generic_device_name_present",
                    passed=True,
                    severity=SEVERITY_INFO,
                    rule_type=RULE_TYPE_TECHNICAL,
                    message=f"Device name '{device_name}' present.",
                )
            )

        return results
