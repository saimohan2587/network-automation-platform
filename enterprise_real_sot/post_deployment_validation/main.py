"""Central orchestrator for Network-as-Code Compliance Layer."""

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from datetime import datetime

from post_deployment_validation.artifact_manager import ArtifactManager
from post_deployment_validation.collectors.base_collector import DeviceUnreachableError
from post_deployment_validation.collectors.factory import CollectorFactory
from post_deployment_validation.comparator import StateComparator
from post_deployment_validation.logger import get_logger
from post_deployment_validation.report import (
    ComplianceFieldResult,
    ComplianceSummary,
    DeviceComplianceResult,
    ResourceComplianceResult,
)
from post_deployment_validation.resources.registry import ResourceRegistry
from deployment.context_builder import ContextBuilder
from deployment.credentials import CredentialResolver
from deployment.device_selector import DeviceSelector
from deployment.netbox_client import NetBoxClient

logger = get_logger("ComplianceMain")


@dataclass(frozen=True)
class ComplianceRequest:
    """Inputs required to orchestrate one compliance workflow."""

    selection_criteria: Mapping[str, Any]
    connection_details: Optional[Mapping[str, Mapping[str, Any]]] = None
    requested_protocols: Optional[Sequence[str]] = None
    requested_interfaces: Optional[Sequence[str]] = None
    batch_name: Optional[str] = None


class ComplianceOrchestrator:
    """Decoupled orchestrator coordinating selection, context, collection, and compliance evaluation.

    Contains ZERO protocol-specific, vendor-specific, or device-role hardcoding.
    Delegates all protocol behavior to ResourceRegistry and BaseResource plugins.
    """

    def __init__(
        self,
        netbox_client: Optional[NetBoxClient] = None,
        device_selector: Optional[DeviceSelector] = None,
        context_builder: Optional[ContextBuilder] = None,
        credential_resolver: Optional[CredentialResolver] = None,
        resource_registry: Optional[ResourceRegistry] = None,
        state_comparator: Optional[StateComparator] = None,
        artifact_manager: Optional[ArtifactManager] = None,
    ) -> None:
        self.netbox_client = netbox_client or NetBoxClient()
        self.device_selector = device_selector or DeviceSelector(self.netbox_client)
        self.context_builder = context_builder or ContextBuilder(self.netbox_client)
        self.credential_resolver = credential_resolver or CredentialResolver()
        self.resource_registry = resource_registry or ResourceRegistry()
        self.state_comparator = state_comparator or StateComparator()
        self.artifact_manager = artifact_manager or ArtifactManager()

    def run(self, request: ComplianceRequest) -> ComplianceSummary:
        """Run compliance evaluation workflow across selected network devices."""
        logger.info("Compliance evaluation started.")

        try:
            selected_devices = self.device_selector.select_devices(
                dict(request.selection_criteria)
            )
        except Exception as error:
            message = f"Device selection failed: {error}"
            logger.error(message)
            return ComplianceSummary(
                selected_device_count=0,
                compliant_device_count=0,
                drifted_device_count=0,
                failed_device_count=1,
                results=[],
            )

        logger.info("Selected %d device(s) for compliance check.", len(selected_devices))

        device_results: List[DeviceComplianceResult] = []
        compliant_count = 0
        drifted_count = 0
        unreachable_count = 0
        failed_count = 0

        for device in selected_devices:
            result = self._evaluate_device(device, request)
            device_results.append(result)

            site = str(device.get("site", {}).get("slug", "hyderabad")) if isinstance(device.get("site"), dict) else "hyderabad"
            role = str(device.get("device_role", {}).get("slug", "access")) if isinstance(device.get("device_role"), dict) else "access"
            dev_name = str(device.get("name", "unknown"))

            # Sole verdict classification point (mirrors DeviceComplianceResult.overall_status):
            # COMPLIANT / DRIFT / UNREACHABLE / FAILED. Nothing outside this package
            # re-derives or renames this classification.
            if result.overall_status == "COMPLIANT":
                compliant_count += 1
            elif result.overall_status == "DRIFT":
                drifted_count += 1
            elif result.overall_status == "UNREACHABLE":
                unreachable_count += 1
            else:
                failed_count += 1

        # Derive batch name from request or selected device name
        batch_name = request.batch_name
        if not batch_name:
            if len(selected_devices) == 1:
                batch_name = str(selected_devices[0].get("name", "single_device"))
            elif "site" in request.selection_criteria:
                batch_name = str(request.selection_criteria.get("site"))
            else:
                batch_name = f"batch_{len(selected_devices)}"

        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Create timestamped artifact folder and write reports
        artifact_dir = self.artifact_manager.create_post_deployment_dir(batch_name)

        summary = ComplianceSummary(
            selected_device_count=len(selected_devices),
            compliant_device_count=compliant_count,
            drifted_device_count=drifted_count,
            failed_device_count=failed_count,
            results=device_results,
            timestamp=timestamp_str,
            batch_name=batch_name,
            artifact_dir=artifact_dir,
            unreachable_device_count=unreachable_count,
        )

        device_dicts = [dev.to_dict() for dev in device_results]

        written_artifacts = self.artifact_manager.write_reports(
            artifact_dir=artifact_dir,
            summary_data=summary.to_dict(),
            device_results=device_dicts,
        )

        logger.info(
            "Compliance evaluation finished: selected=%d compliant=%d drifted=%d unreachable=%d failed=%d (Artifacts: %s)",
            summary.selected_device_count,
            summary.compliant_device_count,
            summary.drifted_device_count,
            summary.unreachable_device_count,
            summary.failed_device_count,
            artifact_dir,
        )
        return summary

    def _evaluate_device(
        self,
        device: Mapping[str, Any],
        request: ComplianceRequest,
    ) -> DeviceComplianceResult:
        """Evaluate compliance for a single target device."""
        device_name = device.get("name", "unknown")

        # Resolve SSH connection parameters and credentials via CredentialResolver
        connection_details = None
        if isinstance(request.connection_details, Mapping):
            connection_details = request.connection_details.get(device_name)

        if not connection_details:
            try:
                connection_details = self.credential_resolver.resolve_connection_details(device)
            except Exception as error:
                message = f"Credential resolution failed: {error}"
                logger.error("%s Device: '%s'.", message, device_name)
                return DeviceComplianceResult(
                    device_name=device_name,
                    ip_address="",
                    resource_results=[],
                    error_message=message,
                )

        host_ip = str(connection_details.get("host", ""))

        try:
            # Build unified context from NetBox
            logger.info("Building deployment context for device '%s'.", device_name)
            device_context = self.context_builder.build_device_context(dict(device))

            # Query dynamic ResourceRegistry for applicable plugins (supports_device AND is_configured)
            applicable_plugins = self.resource_registry.get_applicable_resources(
                device_context,
                request.requested_protocols,
            )

            if not applicable_plugins:
                logger.info("No applicable compliance plugins for device '%s'.", device_name)
                return DeviceComplianceResult(
                    device_name=device_name,
                    ip_address=host_ip,
                    resource_results=[],
                    error_message="No applicable configured compliance plugins found for target selection.",
                )

            resource_results: List[ResourceComplianceResult] = []

            for plugin in applicable_plugins:
                logger.info(
                    "Evaluating resource '%s' for device '%s'...",
                    plugin.resource_name,
                    device_name,
                )

                # 1. Extract desired state map from NetBox context
                desired_state = plugin.extract_desired_state(
                    device_context,
                    request.requested_interfaces,
                )

                # 2. Get list of read-only collection requests (show commands)
                requests = plugin.get_collection_requests(device_context, desired_state)
                if not requests:
                    continue

                # 3. Instantiate read-only collector via factory and fetch actual raw outputs over SSH
                collector = CollectorFactory.get_collector(connection_details)
                raw_outputs = collector.collect(device_name, connection_details, requests)

                # 4. Parse raw output into normalized actual state map
                actual_state = plugin.parse_actual_state(raw_outputs, device_context, desired_state)

                # 5. Execute generic recursive comparison between desired and actual state maps
                raw_comparisons = self.state_comparator.compare(desired_state, actual_state)

                # 6. Group raw field comparisons into structured ResourceComplianceResult objects
                resource_results.extend(
                    self._group_comparisons_by_scope(
                        plugin.resource_name, raw_comparisons
                    )
                )

            return DeviceComplianceResult(
                device_name=device_name,
                ip_address=host_ip,
                resource_results=resource_results,
            )

        except DeviceUnreachableError as error:
            # The device could not be reached at all -- classify as UNREACHABLE,
            # never the generic FAILED verdict (see DeviceComplianceResult.overall_status).
            message = str(error)
            logger.error("%s Device: '%s'.", message, device_name)
            return DeviceComplianceResult(
                device_name=device_name,
                ip_address=host_ip,
                resource_results=[],
                error_message=message,
                unreachable=True,
            )

        except Exception as error:
            message = f"Compliance evaluation failed: {error}"
            logger.error("%s Device: '%s'.", message, device_name)
            return DeviceComplianceResult(
                device_name=device_name,
                ip_address=host_ip,
                resource_results=[],
                error_message=message,
            )

    @staticmethod
    def _group_comparisons_by_scope(
        resource_name: str,
        comparisons: Sequence[Any],
    ) -> List[ResourceComplianceResult]:
        """Group field-level comparison results into ResourceComplianceResult instances by scope/interface."""
        scoped_fields: Dict[str, List[ComplianceFieldResult]] = {}

        for comp in comparisons:
            path_parts = comp.field_path.split(".")
            if len(path_parts) >= 3 and path_parts[0] == "interfaces":
                scope_name = path_parts[1]
                field_name = ".".join(path_parts[2:])
            else:
                scope_name = "global"
                field_name = comp.field_path

            field_result = ComplianceFieldResult(
                field_name=field_name,
                expected=comp.expected_value,
                actual=comp.actual_value,
                status=comp.status,
                reason=comp.reason,
            )

            scoped_fields.setdefault(scope_name, []).append(field_result)

        results: List[ResourceComplianceResult] = []
        for scope_name in sorted(scoped_fields):
            results.append(
                ResourceComplianceResult(
                    resource_name=resource_name,
                    scope_name=scope_name,
                    field_results=scoped_fields[scope_name],
                )
            )

        return results
