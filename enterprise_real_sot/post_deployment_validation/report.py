"""Compliance reporting dataclasses and CLI summary output formatters."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class ComplianceFieldResult:
    """Field-level evaluation outcome."""

    field_name: str
    expected: Any
    actual: Any
    status: str  # "PASS" or "DRIFT"
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "field_name": self.field_name,
            "expected": self.expected,
            "actual": self.actual,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ResourceComplianceResult:
    """Resource-level evaluation outcome for a specific scope (e.g. interface or global)."""

    resource_name: str
    scope_name: str
    field_results: Sequence[ComplianceFieldResult]

    @property
    def status(self) -> str:
        """Return 'DRIFT' if any field drifted, else 'PASS'."""
        for field in self.field_results:
            if field.status == "DRIFT":
                return "DRIFT"
        return "PASS"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "resource_name": self.resource_name,
            "scope_name": self.scope_name,
            "status": self.status,
            "field_results": [f.to_dict() for f in self.field_results],
        }


@dataclass(frozen=True)
class DeviceComplianceResult:
    """Aggregated evaluation outcome for a target network device."""

    device_name: str
    ip_address: str
    resource_results: Sequence[ResourceComplianceResult]
    error_message: Optional[str] = None

    @property
    def overall_status(self) -> str:
        """Return 'DRIFT' if any resource drifted or an error occurred, else 'COMPLIANT'."""
        if self.error_message:
            return "FAILED"
        for resource in self.resource_results:
            if resource.status == "DRIFT":
                return "DRIFT"
        return "COMPLIANT"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "device_name": self.device_name,
            "ip_address": self.ip_address,
            "overall_status": self.overall_status,
            "error_message": self.error_message,
            "resource_results": [r.to_dict() for r in self.resource_results],
        }


@dataclass(frozen=True)
class ComplianceSummary:
    """Aggregated summary of a compliance check across all target devices."""

    selected_device_count: int
    compliant_device_count: int
    drifted_device_count: int
    failed_device_count: int
    results: Sequence[DeviceComplianceResult]
    timestamp: str = ""
    batch_name: str = ""
    artifact_dir: Optional[Path] = None
    written_artifacts: Optional[Dict[str, Path]] = None

    @property
    def total_drifts(self) -> int:
        """Calculate total number of individual field drifts across all devices."""
        total = 0
        for dev in self.results:
            for res in dev.resource_results:
                for field in res.field_results:
                    if field.status == "DRIFT":
                        total += 1
        return total

    @property
    def drift_summary(self) -> Dict[str, int]:
        """Count number of field drifts per protocol."""
        summary: Dict[str, int] = {}
        for dev in self.results:
            for res in dev.resource_results:
                for field in res.field_results:
                    if field.status == "DRIFT":
                        summary[res.resource_name] = summary.get(res.resource_name, 0) + 1
        return summary

    def to_dict(self) -> Dict[str, Any]:
        """Serialize batch-level summary to dictionary."""
        return {
            "execution_time": self.timestamp,
            "device_count": self.selected_device_count,
            "checked_devices": self.selected_device_count,
            "compliant_devices": self.compliant_device_count,
            "drifted_devices": self.drifted_device_count,
            "ssh_failed_devices": self.failed_device_count,
            "total_drifts": self.total_drifts,
            "drift_summary": self.drift_summary,
        }


class ComplianceReporter:
    """Formatter for compliance evaluation reports."""

    @staticmethod
    def print_preflight_summary(
        criteria: Any,
        protocols: List[str],
        interfaces: List[str],
    ) -> None:
        """Print pre-flight evaluation summary."""
        print("\n================ PRE-FLIGHT COMPLIANCE SUMMARY ================")
        print(f"  Target Selection Criteria : {criteria}")
        print(f"  Target Protocols Filter   : {', '.join(protocols)}")
        print(f"  Target Interfaces Filter  : {', '.join(interfaces)}")
        print(f"  Execution Mode            : READ-ONLY (No Device Configuration)")
        print("=================================================================\n")

    @classmethod
    def print_execution_results(cls, summary: ComplianceSummary) -> None:
        """Print concise CLI compliance evaluation summary."""
        print("\nPost-Deployment Validation Completed\n")

        print(f"Devices Checked : {summary.selected_device_count}")
        print(f"Drifted Devices : {summary.drifted_device_count}")
        print(f"Total Drifts    : {summary.total_drifts}\n")

        if summary.artifact_dir:
            try:
                parts = summary.artifact_dir.parts
                if "artifacts" in parts:
                    idx = parts.index("artifacts")
                    display_path = Path(*parts[idx:])
                else:
                    display_path = summary.artifact_dir
            except Exception:
                display_path = summary.artifact_dir
            print(f"Artifacts:\n{display_path}/\n")
