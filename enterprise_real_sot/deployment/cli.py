"""
Purpose   : Command-line entry point for Network-as-Code deployment pipeline.
Called By : User terminal (`python -m deployment.cli --devices <device> --dry-run`).
Calls Next: deployment/main.py (`DeploymentOrchestrator.run()`).
"""

import argparse
import sys
from typing import Any, Dict, List, Sequence, Tuple

from deployment.logger import get_logger
from deployment.main import DeploymentOrchestrator, DeploymentRequest, DeploymentSummary


# Initialize logger for CLI execution module
logger = get_logger("DeploymentCLI")


def parse_args(args: Sequence[str]) -> argparse.Namespace:
    """Parse deployment CLI arguments."""
    # Create argument parser with description and usage examples
    parser = argparse.ArgumentParser(
        description="Network-as-Code Enterprise Deployment Pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m deployment.cli --devices sw-access-01 --protocols port_security --interfaces GigabitEthernet3/0/5 --dry-run
  python -m deployment.cli --devices sw-access-01,sw-access-02 --protocols port_security --dry-run
  python -m deployment.cli --devices site:hyderabad --protocols all --dry-run
  python -m deployment.cli --devices sw-access-01 --protocols port_security --save-config
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
    # Define optional --exclude-interfaces argument
    parser.add_argument(
        "--exclude-interfaces",
        default="",
        help="Comma-separated interface names to exclude from configuration deployment (e.g. 'GigabitEthernet3/0/1').",
    )
    # Define optional --save-config flag to execute 'write memory' after deployment
    parser.add_argument(
        "-s",
        "--save-config",
        action="store_true",
        help="Save running configuration to startup configuration on the switch after deploying.",
    )
    # Define optional --dry-run flag to perform in-memory simulation without SSH
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate context building and configuration rendering without establishing SSH connections or modifying switches.",
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
        return {"name": device_list}

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


def parse_excluded_interfaces(excluded_input: str) -> List[str]:
    """Parse comma-separated excluded interfaces string into list."""
    if not excluded_input or not excluded_input.strip():
        return []
    return [item.strip() for item in excluded_input.strip().split(",") if item.strip()]


def print_preflight_summary(
    criteria: Dict[str, Any],
    protocols: List[str],
    interfaces: List[str],
    excluded_interfaces: List[str],
    save_config: bool,
    dry_run: bool,
) -> None:
    """Display pre-flight summary report before initiating operations."""
    # Print formatted pre-flight summary header and target parameters
    print("\n================ PRE-FLIGHT DEPLOYMENT SUMMARY ================")
    print(f"  Target Selection Criteria : {criteria}")
    print(f"  Target Protocol Plugins   : {', '.join(protocols)}")
    print(f"  Target Interfaces         : {', '.join(interfaces)}")
    print(f"  Excluded Interfaces       : {', '.join(excluded_interfaces) if excluded_interfaces else 'None'}")
    print(f"  Save Configuration        : {'YES' if save_config else 'NO'}")
    print(f"  Dry-Run Mode              : {'YES (Safety Mode — No SSH)' if dry_run else 'NO (Live Execution)'}")
    print("=================================================================\n")


def print_execution_results(summary: DeploymentSummary, dry_run: bool) -> None:
    """Display deployment execution results report."""
    if dry_run:
        print("\nDry Run Completed\n")
        artifact_dir_path = getattr(summary, "artifact_dir", None)
        if artifact_dir_path:
            from pathlib import Path
            p = Path(artifact_dir_path)
            try:
                # Format relative path starting from artifacts/
                parts = p.parts
                if "artifacts" in parts:
                    idx = parts.index("artifacts")
                    display_path = Path(*parts[idx:])
                else:
                    display_path = p
            except Exception:
                display_path = p
            print(f"Artifacts:\n{display_path}/\n")
        else:
            print("Artifacts:\nNone\n")

        print("Summary:\nsummary.txt\n")

        print("Generated Configurations:")
        candidate_count = 0
        for result in summary.results:
            if result.connection_status != "not_connected":
                print(f"{result.device_name}.cfg")
                candidate_count += 1
        if candidate_count == 0:
            print("(No configurations generated)")

        skipped_assessments = [
            res for res in getattr(summary, "assessment_results", ()) if not res.is_candidate
        ]
        if skipped_assessments:
            print("\nSkipped Devices:")
            for skipped in skipped_assessments:
                print(f"  {skipped.device_name} - Reason: {skipped.failure_reason or 'Validation Failed'}")

        print("\n=================================================================\n")
        return

    # In live execution mode, print execution stats and errors
    print("\n=================================================")
    print("Deployment Execution Summary")
    print("=================================================")

    for result in summary.results:
        desired_cnt = getattr(result, "desired_items_count", 0)
        compliant_cnt = getattr(result, "compliant_items_count", 0)
        change_req = getattr(result, "change_required_count", 0)
        cmds_sent = getattr(result, "commands_sent", 0)
        backup_stat = "SUCCESS" if getattr(result, "backup_saved", False) else "SKIPPED/FAILED"
        dep_stat = "SUCCESS" if result.deployment_status == "success" else "FAILED"
        post_verif = getattr(result, "verification_status", "SKIPPED")
        rollback_stat = getattr(result, "rollback_status", "NOT_REQUIRED")

        print(f"Device                 : {result.device_name}")
        print(f"Management IP          : {result.ip_address or 'Unknown'}")
        print(f"Desired Items          : {desired_cnt}")
        print(f"Already Compliant      : {compliant_cnt}")
        print(f"Change Required        : {change_req}")
        print(f"Commands Sent          : {cmds_sent}")
        print(f"Commands Successful    : {cmds_sent if result.deployment_status == 'success' else 0}")
        print(f"Commands Failed        : {0 if result.deployment_status == 'success' else cmds_sent}")
        print(f"Backup                 : {backup_stat}")
        print(f"Deployment             : {dep_stat}")
        print(f"Post Verification      : {post_verif}")
        print(f"Rollback               : {rollback_stat}")
        print(f"Final Lifecycle State  : {result.state or 'UNKNOWN'}")
        if result.error_message and result.state != "DRY_RUN":
            print(f"Error Message          : {result.error_message}")
        print("-------------------------------------------------")

    print("=================================================================\n")



def main(raw_args: Sequence[str] = None) -> int:
    """CLI execution entry point."""
    # Use command-line arguments if none were explicitly passed
    if raw_args is None:
        raw_args = sys.argv[1:]

    # Parse raw arguments into structured namespace
    args = parse_args(raw_args)

    # Parse device selection criteria, protocol list, interface list, and excluded interfaces
    selection_criteria = parse_selection_criteria(args.devices)
    protocols = parse_list_input(args.protocols)
    interfaces = parse_list_input(args.interfaces)
    excluded_interfaces = parse_excluded_interfaces(args.exclude_interfaces)

    # Display pre-flight deployment summary report
    print_preflight_summary(
        criteria=selection_criteria,
        protocols=protocols,
        interfaces=interfaces,
        excluded_interfaces=excluded_interfaces,
        save_config=args.save_config,
        dry_run=args.dry_run,
    )

    # Build deployment request object
    request = DeploymentRequest(
        selection_criteria=selection_criteria,
        connection_details=None,  # Dynamic credential & IP resolution via CredentialResolver
        requested_protocols=protocols,
        requested_interfaces=interfaces,
        excluded_interfaces=excluded_interfaces,
        save_config=args.save_config,
        dry_run=args.dry_run,
    )

    # Instantiate deployment orchestrator and execute request
    orchestrator = DeploymentOrchestrator()
    summary = orchestrator.run(request)

    # Display final execution results report
    print_execution_results(summary, dry_run=args.dry_run)

    # Return exit code 0 for success, 1 for failures
    return 0 if summary.failed_device_count == 0 else 1


if __name__ == "__main__":
    # Execute main entry point when script is run directly
    sys.exit(main())
