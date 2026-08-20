"""Staging live device discovery and lifecycle orchestrator for device_migration package."""

import os
import json
import yaml
from typing import Dict, Any, List, Optional

from deployment.netbox_client import NetBoxClient
from deployment.device_selector import DeviceSelector
from deployment.credentials import CredentialResolver
from device_migration.collector import MigrationCollector
from device_migration.parser_engine import MigrationParserEngine
from device_migration.logger import get_logger

logger = get_logger("StagingDiscoveryEngine")


class StagingDiscoveryEngine:
    """
    Orchestrates the 6-stage lifecycle for live staging devices:
    Collect -> Parse -> Classify -> Store Artifacts -> Review Gate -> Dry-Run / Commit to NetBox.
    """

    DISCOVERY_COMMANDS = [
        "show running-config",
        "show ip interface brief",
        "show interfaces",
        "show vlan brief",
        "show version"
    ]

    def __init__(
        self,
        manifest_path: str = "config/migration/gns3_staging_discovery.yaml",
        discovery_only: bool = True,
        dry_run: bool = True,
        commit: bool = False
    ):
        self.manifest_path = os.path.abspath(manifest_path)
        if not os.path.exists(self.manifest_path):
            raise FileNotFoundError(f"Staging discovery manifest not found: {self.manifest_path}")

        with open(self.manifest_path, "r", encoding="utf-8") as f:
            self.manifest_data = yaml.safe_load(f) or {}

        self.discovery_only = discovery_only
        self.dry_run = False if commit else dry_run
        self.commit = commit

        self.client = NetBoxClient()
        self.selector = DeviceSelector(self.client)
        self.resolver = CredentialResolver()
        self.collector = MigrationCollector()
        self.base_artifact_dir = os.path.abspath("artifacts/migration/gns3_staging")
        os.makedirs(self.base_artifact_dir, exist_ok=True)

    def run_discovery(self) -> Dict[str, Any]:
        """Execute the 6-stage discovery pipeline across all staging devices."""
        staging_devices = self.manifest_data.get("staging_devices", [])
        if not staging_devices:
            logger.warning("No staging devices found in manifest '%s'", self.manifest_path)
            return {"status": "EMPTY", "processed": 0}

        results = {}

        for dev_entry in staging_devices:
            if not dev_entry.get("enabled", True):
                logger.info("Skipping disabled staging device '%s'", dev_entry.get("name"))
                continue

            device_name = dev_entry.get("name")
            logger.info("==================================================")
            logger.info("STAGE 1: Executing Read-Only SSH Collection for '%s'...", device_name)

            try:
                # 1. Resolve Connection Parameters (IP & SSH Credentials from .env)
                conn_details = {
                    "host": dev_entry.get("ip", "").split("/")[0],
                    "username": os.getenv(f"SSH_{device_name.upper()}_USERNAME", os.getenv("SSH_USERNAME", "admin")),
                    "password": os.getenv(f"SSH_{device_name.upper()}_PASSWORD", os.getenv("SSH_PASSWORD", "admin")),
                    "secret": os.getenv(f"SSH_{device_name.upper()}_SECRET", os.getenv("SSH_SECRET", "admin")),
                    "device_type": "cisco_ios",
                    "port": int(os.getenv("SSH_PORT", 22)),
                    "timeout": int(os.getenv("SSH_TIMEOUT", 30))
                }

                # STAGE 1: Collect (Read-Only SSH)
                raw_outputs = self.collector.collector.collect(device_name, conn_details, self.DISCOVERY_COMMANDS)

                # STAGE 2: Parse
                logger.info("STAGE 2: Parsing live CLI output for '%s'...", device_name)
                discovered_interfaces = MigrationParserEngine.parse_discovered_interfaces(raw_outputs)
                protocol_data = MigrationParserEngine.parse_all_protocols(raw_outputs)

                # STAGE 3: Classify
                logger.info("STAGE 3: Classifying SOT intent for '%s'...", device_name)
                staged_intent = {
                    "device_name": device_name,
                    "management_ip": dev_entry.get("ip"),
                    "dcim": {
                        "interfaces": discovered_interfaces,
                        "vlans": protocol_data.get("vlans", [])
                    },
                    "ipam": {
                        "ip_addresses": [
                            {"address": intf["ip_address"], "interface": intf["name"]}
                            for intf in discovered_interfaces if intf.get("ip_address")
                        ]
                    }
                }

                # STAGE 4: Store Artifacts
                dev_artifact_dir = os.path.join(self.base_artifact_dir, device_name)
                os.makedirs(dev_artifact_dir, exist_ok=True)

                raw_path = os.path.join(dev_artifact_dir, "raw_outputs.json")
                with open(raw_path, "w", encoding="utf-8") as f:
                    json.dump(raw_outputs, f, indent=2)

                dataset_path = os.path.join(dev_artifact_dir, "migration_dataset.json")
                with open(dataset_path, "w", encoding="utf-8") as f:
                    json.dump({"interfaces": discovered_interfaces, "protocols": protocol_data}, f, indent=2)

                intent_path = os.path.join(dev_artifact_dir, "staged_migration_intent.json")
                with open(intent_path, "w", encoding="utf-8") as f:
                    json.dump(staged_intent, f, indent=2)

                logger.info("STAGE 4: Artifacts stored successfully in '%s'", dev_artifact_dir)

                # STAGE 5: Dry-Run Payload Generation (No NetBox Mutations)
                dry_run_payloads = {
                    "device": {"name": device_name, "status": "active"},
                    "interfaces_to_create": [intf["name"] for intf in discovered_interfaces],
                    "ips_to_assign": [intf["ip_address"] for intf in discovered_interfaces if intf.get("ip_address")]
                }

                payload_path = os.path.join(dev_artifact_dir, "dry_run_netbox_payloads.json")
                with open(payload_path, "w", encoding="utf-8") as f:
                    json.dump(dry_run_payloads, f, indent=2)

                # STAGE 6: Commit Gate (Only if --commit is explicitly passed)
                if self.commit:
                    logger.info("STAGE 6: Explicit --commit flag passed. Syncing to NetBox...")
                    self.sync_staged_intent_to_netbox(staged_intent, dev_entry)
                else:
                    logger.info("STAGE 5 & 6: Discovery and Artifact Generation complete. NetBox DB untouched (Dry-Run mode).")

                results[device_name] = {
                    "status": "SUCCESS",
                    "interface_count": len(discovered_interfaces),
                    "artifact_dir": dev_artifact_dir,
                    "committed_to_netbox": self.commit
                }

            except Exception as e:
                logger.error("Discovery failed for staging device '%s': %s", device_name, e, exc_info=True)
                results[device_name] = {
                    "status": "FAILED",
                    "error": str(e)
                }

        return results

    def sync_staged_intent_to_netbox(self, staged_intent: Dict[str, Any], dev_entry: Dict[str, Any]) -> Dict[str, Any]:
        """Commit staged intent artifacts directly to NetBox REST API."""
        device_name = staged_intent["device_name"]
        mgmt_ip = staged_intent.get("management_ip", "")

        site_res = self.client.get("dcim/sites/", {"slug": dev_entry.get("site", "hyderabad")})
        site_id = site_res["results"][0]["id"]

        platform_res = self.client.get("dcim/platforms/", {"slug": "cisco-ios"})
        platform_id = platform_res["results"][0]["id"]

        device_type_res = self.client.get("dcim/device-types/", {"slug": "ws-c3750x-24p"})
        device_type_id = device_type_res["results"][0]["id"]

        role_slug = "core-switch" if "R1" in device_name else "layer-2-access-switch"
        role_res = self.client.get("dcim/device-roles/", {"slug": role_slug})
        role_id = role_res["results"][0]["id"]

        # 1. Create or fetch Device
        dev_res = self.client.get("dcim/devices/", {"name": device_name})
        if dev_res.get("results"):
            device_obj = dev_res["results"][0]
            logger.info("Device '%s' already exists in NetBox (ID: %s)", device_name, device_obj["id"])
        else:
            device_obj = self.client.post("dcim/devices/", {
                "name": device_name,
                "role": role_id,
                "device_type": device_type_id,
                "site": site_id,
                "platform": platform_id,
                "status": "active"
            })
            logger.info("Created device '%s' in NetBox (ID: %s)", device_name, device_obj["id"])

        device_id = device_obj["id"]

        # 2. Synchronize Discovered Interfaces
        created_interfaces = {}
        for intf_data in staged_intent.get("dcim", {}).get("interfaces", []):
            intf_name = intf_data["name"]
            intf_type = "virtual" if "vlan" in intf_name.lower() or "loopback" in intf_name.lower() else (
                "100base-tx" if "fast" in intf_name.lower() else "1000base-t"
            )

            existing_intf = self.client.get("dcim/interfaces/", {"device_id": device_id, "name": intf_name})
            if existing_intf.get("results"):
                intf_obj = existing_intf["results"][0]
                self.client.patch(f"dcim/interfaces/{intf_obj['id']}/", {
                    "enabled": intf_data.get("enabled", True),
                    "description": intf_data.get("description", "")
                })
            else:
                intf_obj = self.client.post("dcim/interfaces/", {
                    "device": device_id,
                    "name": intf_name,
                    "type": intf_type,
                    "enabled": intf_data.get("enabled", True),
                    "description": intf_data.get("description", "")
                })
                logger.info("Created interface '%s' on device '%s' in NetBox", intf_name, device_name)

            created_interfaces[intf_name] = intf_obj["id"]

        # 3. Synchronize IP Addresses
        primary_ip_obj_id = None
        for ip_data in staged_intent.get("ipam", {}).get("ip_addresses", []):
            ip_addr = ip_data["address"]
            bound_intf_name = ip_data["interface"]
            bound_intf_id = created_interfaces.get(bound_intf_name)

            existing_ip = self.client.get("ipam/ip-addresses/", {"address": ip_addr})
            if existing_ip.get("results"):
                ip_obj = existing_ip["results"][0]
                if bound_intf_id and ip_obj.get("assigned_object_id") != bound_intf_id:
                    self.client.patch(f"ipam/ip-addresses/{ip_obj['id']}/", {
                        "assigned_object_type": "dcim.interface",
                        "assigned_object_id": bound_intf_id
                    })
            else:
                ip_obj = self.client.post("ipam/ip-addresses/", {
                    "address": ip_addr,
                    "assigned_object_type": "dcim.interface",
                    "assigned_object_id": bound_intf_id,
                    "status": "active"
                })
                logger.info("Created IP address '%s' assigned to '%s' in NetBox", ip_addr, bound_intf_name)

            if mgmt_ip and ip_addr == mgmt_ip:
                primary_ip_obj_id = ip_obj["id"]

        # 4. Set Primary Management IPv4 Address
        if primary_ip_obj_id:
            self.client.patch(f"dcim/devices/{device_id}/", {"primary_ip4": primary_ip_obj_id})
            logger.info("Set primary_ip4 for device '%s' to '%s' in NetBox", device_name, mgmt_ip)

        return {"device_id": device_id, "interfaces_synced": len(created_interfaces)}
