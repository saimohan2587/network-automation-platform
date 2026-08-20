"""Command-line interface entrypoint for device_migration package."""

import argparse
import sys
import os

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from device_migration.manifest_loader import ManifestLoader
from device_migration.main import MigrationOrchestrator
from device_migration.logger import get_logger

logger = get_logger("CLI")


# build_parser(): Constructs the command-line argument parser.
# Why used: Defines CLI flags to control execution phases (discovery, staging, dry-run, commit).
def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Network-as-Code Enterprise Device Migration Engine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # --manifest flag: Specifies path to input YAML/JSON migration manifest file.
    # Why used: Required to load migration pair mappings, site info, and regex transformation rules.
    parser.add_argument(
        "--manifest",
        type=str,
        required=True,
        help="Path to YAML/JSON migration manifest file (e.g. config/migration/hyderabad_access_switches.yaml)"
    )

    # --discovery-only flag: Runs read-only SSH collection from legacy switch without NetBox updates.
    # Why used: Used to safely audit live switch state and test parsing without touching NetBox or target hardware.
    parser.add_argument(
        "--discovery-only",
        action="store_true",
        default=False,
        help="Execute read-only SSH discovery and artifact generation without modifying NetBox or devices."
    )

    # --stage-intent flag: Evaluates classification policy to create staged target proposal.
    # Why used: Organizes raw switch data into Global, Local, DCIM, and IPAM scopes before NetBox population.
    parser.add_argument(
        "--stage-intent",
        action="store_true",
        default=True,
        help="Evaluate SOT classification policy and export staged_migration_intent.json artifact."
    )

    # --populate-netbox flag: Enables NetBox SOT population plan generation and commit capabilities.
    # Why used: Triggers NetBox REST API resolution for dry-run diff calculation or database population.
    parser.add_argument(
        "--populate-netbox",
        action="store_true",
        default=False,
        help="Generate NetBox SOT dry-run plans or commit population updates to NetBox."
    )

    # --dry-run flag: Pre-computes NetBox REST API PATCH payloads without modifying NetBox database.
    # Why used: Safety mechanism to verify proposed REST API updates and endpoint IDs before committing.
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Generate dry-run REST API payloads diff without modifying NetBox DB (Default: True)."
    )

    # --commit flag: Applies actual REST API PATCH updates to NetBox SOT database.
    # Why used: Executes final database population once staged intent and dry-run payloads are approved.
    parser.add_argument(
        "--commit",
        action="store_true",
        default=False,
        help="Execute NetBox REST API commit updates (Requires explicit user confirmation)."
    )

    return parser


# main(): Entrypoint function executed when running the CLI module.
# Why used: Orchestrates argument parsing, manifest loading, orchestrator execution, and exit codes.
def main():
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        if "staging" in args.manifest or "gns3" in args.manifest:
            from device_migration.discovery_engine import StagingDiscoveryEngine
            logger.info("Detected staging discovery manifest '%s'. Invoking StagingDiscoveryEngine...", args.manifest)
            engine = StagingDiscoveryEngine(
                manifest_path=args.manifest,
                discovery_only=args.discovery_only,
                dry_run=args.dry_run,
                commit=args.commit
            )
            results = engine.run_discovery()
            logger.info("Staging discovery complete. Results: %s", results)
            sys.exit(0)

        # ManifestLoader.load(): Loads and validates the YAML/JSON manifest file.
        # Why used: Converts raw YAML file into structured MigrationManifest dataclass object.
        manifest = ManifestLoader.load(args.manifest)

        # Disables dry-run mode when --commit is explicitly passed by the user.
        dry_run = False if args.commit else args.dry_run

        # MigrationOrchestrator(...): Instantiates the core migration pipeline engine with CLI flags.
        # Why used: Initializes NetBox client, SSH collector, interface mapper, and populator services.
        orchestrator = MigrationOrchestrator(
            manifest,
            discovery_only=args.discovery_only,
            stage_intent=args.stage_intent,
            populate_netbox=args.populate_netbox,
            dry_run=dry_run,
            commit=args.commit
        )

        # orchestrator.run(): Triggers execution of the migration pipeline across all device pairs.
        # Why used: Runs discovery, parsing, hardware mapping, intent staging, dry-run, and commit steps.
        summary = orchestrator.run()

        # Exit code 1 if any migration pair failed, exit code 0 on complete success.
        if summary.get("failed_pairs", 0) > 0:
            logger.warning("Batch completed with %d failed pair(s). See summary report.", summary["failed_pairs"])
            sys.exit(1)
        else:
            logger.info("Batch completed successfully for all %d pair(s).", summary["total_pairs"])
            sys.exit(0)

    except Exception as err:
        logger.error("Migration execution halted due to critical error: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
