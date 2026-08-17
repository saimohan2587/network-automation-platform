"""MigrationOrchestrator for device_migration package."""

import sys
import json
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional

from deployment.netbox_client import NetBoxClient
from deployment.device_selector import DeviceSelector
from deployment.credentials import CredentialResolver
from device_migration.manifest_loader import MigrationManifest, MigrationPair
from device_migration.interface_mapper import InterfaceMapper, MappedInterface
from device_migration.collector import MigrationCollector
from device_migration.parser_engine import MigrationParserEngine
from device_migration.artifact_manager import MigrationArtifactManager
from device_migration.populator import NetBoxPopulator
from device_migration.logger import get_logger

logger = get_logger("MigrationOrchestrator")


class MigrationOrchestrator:
    """Orchestrates discovery, mapping, and report generation for migration manifests."""

    def __init__(
        self,
        manifest: MigrationManifest,
        discovery_only: bool = False,
        stage_intent: bool = True,
        populate_netbox: bool = False,
        dry_run: bool = True,
        commit: bool = False
    ):
        self.manifest = manifest
        self.discovery_only = discovery_only
        self.stage_intent = stage_intent
        self.populate_netbox = populate_netbox
        self.dry_run = dry_run
        self.commit = commit
        self.netbox_client = NetBoxClient()
        self.selector = DeviceSelector(self.netbox_client)
        self.resolver = CredentialResolver()
        self.collector = MigrationCollector()
        self.populator = NetBoxPopulator(self.netbox_client)
        self.artifact_mgr = MigrationArtifactManager(manifest.batch_name)

    def run(self) -> Dict[str, Any]:
        """Execute migration batch across all configured migration pairs with fault isolation."""
        logger.info("Starting migration batch '%s' (%d active pairs)...", self.manifest.batch_name, len(self.manifest.migration_pairs))

        total_pairs = len(self.manifest.migration_pairs)
        successful_pairs = 0
        failed_pairs = 0

        pair_summaries = []

        for index, pair in enumerate(self.manifest.migration_pairs, start=1):
            logger.info("-----------------------------------------------------------------")
            logger.info("[%d/%d] Processing Migration Pair: %s -> %s", index, total_pairs, pair.source_device, pair.target_device)
            logger.info("-----------------------------------------------------------------")

            # FAULT ISOLATION: Each pair runs in its own try-except block
            try:
                pair_result = self._process_single_pair(pair)
                successful_pairs += 1
                pair_summaries.append({
                    "source_device": pair.source_device,
                    "target_device": pair.target_device,
                    "status": "SUCCESS",
                    "mapped_interfaces_count": len(pair_result["interface_mapping"]),
                    "unmapped_interfaces_count": len(pair_result["unmapped_source_interfaces"]),
                    "artifact_directory": pair_result["artifact_dir"]
                })
            except Exception as error:
                failed_pairs += 1
                stack_trace = traceback.format_exc()
                logger.error("FAILED processing pair '%s -> %s': %s", pair.source_device, pair.target_device, error)
                fail_path = self.artifact_mgr.export_pair_failure(pair.source_device, pair.target_device, str(error), stack_trace)
                pair_summaries.append({
                    "source_device": pair.source_device,
                    "target_device": pair.target_device,
                    "status": "FAILED",
                    "error": str(error),
                    "artifact_directory": fail_path
                })

        batch_summary = {
            "batch_name": self.manifest.batch_name,
            "description": self.manifest.description,
            "manifest_file": self.manifest.filepath,
            "mode": "DISCOVERY_ONLY" if self.discovery_only else "FULL",
            "executed_at": datetime.now().isoformat(),
            "total_pairs": total_pairs,
            "successful_pairs": successful_pairs,
            "failed_pairs": failed_pairs,
            "pairs": pair_summaries
        }

        self.artifact_mgr.export_batch_summary(batch_summary)

        logger.info("=================================================================")
        logger.info("Migration Batch Complete. Success: %d, Failed: %d", successful_pairs, failed_pairs)
        logger.info("Artifacts directory: %s", self.artifact_mgr.base_dir)
        logger.info("=================================================================")

        return batch_summary

    def _process_single_pair(self, pair: MigrationPair) -> Dict[str, Any]:
        """Process discovery and hardware mapping for a single migration pair."""
        # Step 1: Select source and target devices from NetBox DCIM
        src_devices = self.selector.select_devices({"name": pair.source_device})
        tgt_devices = self.selector.select_devices({"name": pair.target_device})

        if not src_devices:
            raise ValueError(f"Source device '{pair.source_device}' not found in NetBox.")
        if not tgt_devices:
            raise ValueError(f"Target device '{pair.target_device}' not found in NetBox.")

        src_device = src_devices[0]
        tgt_device = tgt_devices[0]

        # Step 2: Resolve SSH connection credentials for source and target
        src_conn = self.resolver.resolve_connection_details(src_device)
        tgt_conn = self.resolver.resolve_connection_details(tgt_device)

        logger.info("Source IP: %s (%s)", src_conn["host"], src_conn.get("username"))
        logger.info("Target IP: %s (%s)", tgt_conn["host"], tgt_conn.get("username"))

        # Step 3: Execute read-only SSH discovery on source switch
        raw_outputs = self.collector.collect_source_state(pair.source_device, src_conn)

        # Step 4: Parse operational state CLI outputs into structured dictionaries
        raw_config = raw_outputs.get("show running-config", "")
        raw_intf_cfg = MigrationParserEngine.parse_running_config_interfaces(raw_config)
        global_protocols = MigrationParserEngine.parse_all_protocols(raw_outputs)

        # Step 5: Map source switch port names (Gi3/0/1) to target switch port names (Gi1/0/1)
        mapper = InterfaceMapper(self.manifest, pair)
        src_interfaces = list(raw_intf_cfg.keys())
        mapped_matrix, unmapped_source_list = mapper.build_mapping_matrix(src_interfaces)

        # Step 6: Build target interface configurations using mapped names
        target_desired_interfaces = []
        interface_mapping_export = []

        for item in mapped_matrix:
            interface_mapping_export.append({
                "source_interface": item.source_interface,
                "target_interface": item.target_interface if item.mapped else None,
                "mapped": item.mapped,
                "strategy": item.mapping_strategy,
                "notes": item.notes
            })

            if not item.mapped or not item.target_interface:
                continue

            src_cfg = raw_intf_cfg.get(item.source_interface, {})
            psec_cfg = src_cfg.get("port_security", {})

            iface_entry = {
                "name": item.target_interface,
                "description": src_cfg.get("description", ""),
                "mode": src_cfg.get("switchport_mode", "access"),
                "untagged_vlan": src_cfg.get("access_vlan") if src_cfg.get("switchport_mode") == "access" else src_cfg.get("native_vlan", 1),
                "tagged_vlans": src_cfg.get("trunk_allowed_vlans", []),
            }

            if psec_cfg.get("enabled"):
                iface_entry["port_security"] = {
                    "enabled": True,
                    "max_mac_addresses": psec_cfg.get("max_mac_addresses", 1),
                    "violation": psec_cfg.get("violation", "shutdown"),
                    "aging_time": psec_cfg.get("aging_time", 0),
                    "aging_type": psec_cfg.get("aging_type", "absolute")
                }

            target_desired_interfaces.append(iface_entry)

        # Step 7: Combine metadata, global config, and interfaces into migration dataset
        migration_dataset = {
            "metadata": {
                "source_device": pair.source_device,
                "source_ip": src_conn["host"],
                "target_device": pair.target_device,
                "target_ip": tgt_conn["host"],
                "target_management_interface": self.manifest.target_mgmt_interface,
                "preserve_target_mgmt_ip": self.manifest.preserve_target_mgmt_ip,
                "generated_at": datetime.now().isoformat()
            },
            "global_config": global_protocols,
            "interface_mapping": interface_mapping_export,
            "unmapped_source_interfaces": unmapped_source_list,
            "target_desired_interfaces": target_desired_interfaces
        }

        # Step 8: Save raw outputs, migration_dataset.json, and interface_mapping.json to disk
        artifact_dir = self.artifact_mgr.export_pair_artifacts(
            pair.source_device,
            pair.target_device,
            migration_dataset,
            interface_mapping_export,
            raw_outputs
        )

        import os

        # Step 9: Apply policy rules to build staged_migration_intent.json
        staged_intent = self.populator.generate_staged_intent(migration_dataset, interface_mapping_export)

        staged_intent_path = os.path.join(artifact_dir, "staged_migration_intent.json")

        with open(staged_intent_path, "w", encoding="utf-8") as f:
            json.dump(staged_intent, f, indent=2)
        logger.info("Saved Staged Migration Intent proposal to '%s'.", staged_intent_path)

        # Step 10: Calculate NetBox REST API PATCH payloads without database changes
        dry_run_plan = None
        if self.populate_netbox or self.dry_run or self.commit:
            dry_run_plan = self.populator.generate_dry_run_plan(staged_intent)
            dry_run_path = os.path.join(artifact_dir, "dry_run_netbox_payloads.json")
            with open(dry_run_path, "w", encoding="utf-8") as f:
                json.dump(dry_run_plan, f, indent=2)
            logger.info("Saved NetBox Dry-Run Population Plan to '%s'.", dry_run_path)

        # Step 11: Commit REST API updates to NetBox database (if --commit is set)
        commit_result = None
        if self.commit:
            logger.info("Executing NetBox SOT Commit Population for '%s -> %s'...", pair.source_device, pair.target_device)
            commit_result = self.populator.commit_population(staged_intent, dry_run_plan, artifact_dir)
            commit_path = os.path.join(artifact_dir, "commit_result.json")
            with open(commit_path, "w", encoding="utf-8") as f:
                json.dump(commit_result, f, indent=2)
            logger.info("Saved NetBox SOT Commit Result to '%s'.", commit_path)

        return {
            "migration_dataset": migration_dataset,
            "interface_mapping": interface_mapping_export,
            "staged_intent": staged_intent,
            "dry_run_plan": dry_run_plan,
            "commit_result": commit_result,
            "unmapped_source_interfaces": unmapped_source_list,
            "artifact_dir": artifact_dir
        }









# main.py
# │
# ├── MigrationOrchestrator.__init__()        Lines 26–46
# │
# └── run()                                   Line 48
#      │
#      ├── loop through migration pairs       Line 58
#      │
#      └── _process_single_pair()              Line 65
#           │
#           ├── DeviceSelector                 Lines 112–113
#           │
#           ├── CredentialResolver              Lines 124–125
#           │
#           ├── MigrationCollector              Line 131
#           │
#           ├── MigrationParserEngine           Lines 135–136
#           │
#           ├── InterfaceMapper                 Lines 139–141
#           │
#           ├── Build migration_dataset         Lines 143–196
#           │
#           ├── ArtifactManager                 Lines 199–205
#           │
#           ├── NetBoxPopulator
#           │      └── staged intent            Lines 209–216
#           │
#           ├── NetBoxPopulator
#           │      └── dry-run plan              Lines 218–225
#           │
#           └── NetBoxPopulator
#                  └── commit_population()      Lines 227–235
