"""Command-line entry point for Network-as-Code Compliance & Config Drift Layer."""

import argparse
import sys
from typing import Any, Dict, List, Sequence

from post_deployment_validation.logger import get_logger
from post_deployment_validation.main import ComplianceOrchestrator, ComplianceRequest, ComplianceSummary
from post_deployment_validation.report import ComplianceReporter

# Initialize logger for Compliance CLI execution module
logger = get_logger("ComplianceCLI")


def parse_args(args: Sequence[str]) -> argparse.Namespace:
    """Parse compliance CLI arguments."""
    # Create argument parser with description and usage examples
    parser = argparse.ArgumentParser(
        description="Network-as-Code Enterprise Compliance & Config Drift Evaluation CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m post_deployment_validation.cli --devices sw-access-01 --protocols port_security --interfaces GigabitEthernet3/0/5
  python -m post_deployment_validation.cli --devices sw-access-01,sw-access-02 --protocols port_security
  python -m post_deployment_validation.cli --devices site:hyderabad --protocols all
""",
    )
    # Define required --devices argument for selecting target switches
    parser.add_argument(
        "-d",
        "--devices",
        required=True,
        help="Target device(s) selection criteria. Accepts single name ('sw-access-01'), comma-separated names ('sw-access-01,sw-access-02'), or Key:Value NetBox filters ('site:hyderabad', 'role:access').",
    )
    # Define optional --protocols argument (defaults to 'all')
    parser.add_argument(
        "-p",
        "--protocols",
        default="all",
        help="Comma-separated protocol plugin names (e.g. 'port_security', 'ospf') or 'all' (default: 'all').",
    )
    # Define optional --interfaces argument (defaults to 'all')
    parser.add_argument(
        "-i",
        "--interfaces",
        default="all",
        help="Comma-separated interface names (e.g. 'GigabitEthernet3/0/5') or 'all' (default: 'all').",
    )
    # Define optional --batch-name argument
    parser.add_argument(
        "-b",
        "--batch-name",
        default=None,
        help="Optional batch name identifier for timestamped artifact folder naming.",
    )
    # Parse and return command line arguments namespace
    return parser.parse_args(args)


def parse_selection_criteria(devices_input: str) -> Dict[str, Any]:
    """Parse --devices input string into a NetBox query dictionary."""
    # Remove leading and trailing whitespace
    devices_input = devices_input.strip()

    # Case 1: Key:Value NetBox filter expression (e.g., 'site:hyderabad')
    if ":" in devices_input:
        key, value = devices_input.split(":", 1)
        return {key.strip(): value.strip()}

    # Case 2: Comma-separated device name list (e.g., 'sw-access-01,sw-access-02')
    if "," in devices_input:
        device_list = [d.strip() for d in devices_input.split(",") if d.strip()]
        return {"name__in": device_list}

    # Case 3: Single device name (e.g., 'sw-access-01')
    return {"name": devices_input}


def parse_list_input(list_input: str) -> List[str]:
    """Parse comma-separated string list or return ['all']."""
    # Remove leading and trailing whitespace
    cleaned = list_input.strip()

    # If empty or 'all', return default list containing 'all'
    if not cleaned or cleaned.lower() == "all":
        return ["all"]

    # Split comma-separated string into clean items list
    return [item.strip() for item in cleaned.split(",") if item.strip()]


def _exit_code_for(summary: ComplianceSummary) -> int:
    """0 only if every device's verdict was COMPLIANT; DRIFT, UNREACHABLE, and
    FAILED all mean the process must exit non-zero. This reads the counts
    ComplianceOrchestrator already classified -- it never reclassifies a verdict."""
    if (
        summary.drifted_device_count == 0
        and summary.unreachable_device_count == 0
        and summary.failed_device_count == 0
    ):
        return 0
    return 1


def main(raw_args: Sequence[str] = None) -> int:
    """Compliance CLI execution entry point."""
    # Use command-line arguments if none were explicitly passed
    if raw_args is None:
        raw_args = sys.argv[1:]

    # Parse raw arguments into structured namespace
    args = parse_args(raw_args)

    # Parse device selection criteria, protocol list, and interface list
    selection_criteria = parse_selection_criteria(args.devices)
    protocols = parse_list_input(args.protocols)
    interfaces = parse_list_input(args.interfaces)

    # Display pre-flight compliance summary report
    ComplianceReporter.print_preflight_summary(
        criteria=selection_criteria,
        protocols=protocols,
        interfaces=interfaces,
    )

    # Build compliance request object
    request = ComplianceRequest(
        selection_criteria=selection_criteria,
        connection_details=None,  # Dynamic credential & IP resolution via CredentialResolver
        requested_protocols=protocols,
        requested_interfaces=interfaces,
        batch_name=args.batch_name,
    )

    # Instantiate compliance orchestrator and execute request
    orchestrator = ComplianceOrchestrator()
    summary = orchestrator.run(request)

    # Display final compliance evaluation results report
    ComplianceReporter.print_execution_results(summary)

    return _exit_code_for(summary)


if __name__ == "__main__":
    # Execute main entry point when script is run directly
    sys.exit(main())
