"""
Purpose   : Queries NetBox for raw device metadata, interfaces, IP assignments, and Config Contexts, combining them into a unified device context dictionary.
Called By : main.py (`DeploymentOrchestrator._assess_device()`).
Calls Next: config_generator.py (`ConfigGenerator.generate()`).
"""

from typing import Dict, Any, List, Optional
from deployment.netbox_client import NetBoxClient
from deployment.utils import deep_merge
from deployment.logger import get_logger


logger = get_logger("ContextBuilder")

class ContextBuilder:
    """
    Enterprise Context Builder module responsible for collecting all deployment
    context data from NetBox for a target device and merging it into a single,
    unified hierarchical context dictionary.
    """

    def __init__(self, netbox_client: NetBoxClient):
        # Inject the NetBox REST client dependency so ContextBuilder can perform API queries.
        self.client = netbox_client

    def _fetch_config_context_data(self, name: str) -> Dict[str, Any]:
        """
        Queries NetBox for a specific named Config Context and returns its payload data.
        """
        try:
            # Query NetBox extras API for a specific named context payload (e.g., "Global-Defaults").
            contexts = self.client.get("extras/config-contexts/", {"name": name})
            # Ensure NetBox returned at least one matching Config Context object before accessing results.
            if contexts and contexts.get("count", 0) > 0:
                return contexts["results"][0].get("data", {})
        except Exception as e:
            logger.warning(f"Could not retrieve Config Context '{name}': {e}")
        return {}

    def _get_device_interfaces_and_ips(self, device_id: int) -> Dict[str, Dict[str, Any]]:
        """
        Queries NetBox for all interfaces and IP addresses belonging to a target device
        and correlates them into a unified dictionary structured by interface name.
        """
        # Fetch all physical and logical interface records (Ethernet, Vlan, LAG) for this device from NetBox DCIM.
        interfaces_raw = self.client.get_all("dcim/interfaces/", {"device_id": device_id})
        
        # Fetch all IP address records assigned to this device from NetBox IPAM.
        ips_raw = self.client.get_all("ipam/ip-addresses/", {"device_id": device_id})

        # Map interface IDs to their structured properties for quick lookup during IP correlation.
        interface_map: Dict[int, Dict[str, Any]] = {}
        structured_interfaces: Dict[str, Dict[str, Any]] = {}

        for intf in interfaces_raw:
            intf_id = intf["id"]
            intf_name = intf["name"]
            
            # Extract parent LAG (EtherChannel) name if this interface is a member of a port bundle.
            lag_info = intf.get("lag")
            lag_name = lag_info.get("name") if lag_info else None

            # Extract untagged/native VLAN ID assigned to this interface.
            untagged_vlan = intf.get("untagged_vlan")
            untagged_vid = untagged_vlan.get("vid") if untagged_vlan else None

            # Extract list of allowed tagged VLAN IDs for trunk mode interfaces.
            tagged_vlans = intf.get("tagged_vlans") or []
            tagged_vids = [v.get("vid") for v in tagged_vlans if v.get("vid")]

            intf_data = {
                "id": intf_id,
                "name": intf_name,
                "description": intf.get("description", ""),
                "enabled": intf.get("enabled", True),
                "type": intf.get("type", {}).get("value"),
                "mode": intf.get("mode", {}).get("value") if intf.get("mode") else None,
                "untagged_vlan": untagged_vid,
                "tagged_vlans": tagged_vids,
                "lag": lag_name,
                "custom_fields": intf.get("custom_fields", {}),
                "ip_addresses": []
            }
            interface_map[intf_id] = intf_data
            structured_interfaces[intf_name] = intf_data

        # Correlate IPAM IP addresses with their assigned DCIM interface ID.
        for ip in ips_raw:
            assigned_obj = ip.get("assigned_object")
            if assigned_obj and ip.get("assigned_object_id"):
                intf_id = ip["assigned_object_id"]
                if intf_id in interface_map:
                    interface_map[intf_id]["ip_addresses"].append(ip["address"])

        return structured_interfaces

    def build_device_context(self, device: Dict[str, Any]) -> Dict[str, Any]:
        """
        Collects Global Defaults, Site Defaults, Device local_context_data, and
        Interface/IP mappings from NetBox and builds one merged, unified context.
        """
        device_id = device["id"]
        device_name = device["name"]
        logger.info(f"Building unified context for device '{device_name}' (ID: {device_id})...")

        # Step 1: Fetch Global defaults baseline (shared across the entire enterprise).
        global_context = self._fetch_config_context_data("Global-Defaults")

        # Step 2: Fetch Site-specific defaults based on the device's site location.
        site_slug = device.get("site", {}).get("slug", "")
        site_context = {}
        if site_slug:
            site_context_name = f"Site-Defaults-{site_slug}"
            site_context = self._fetch_config_context_data(site_context_name)

        # Step 3: Extract Device-local context data specific to this single switch.
        device_context_name = f"Device-{device_name}"
        device_config_context = self._fetch_config_context_data(device_context_name)
        device_local_context = deep_merge(device_config_context, device.get("local_context_data") or {})

        # Step 4: Merge hierarchy in order: Global < Site < Device Context < Device Local.
        merged_config = deep_merge(global_context, site_context)
        merged_config = deep_merge(merged_config, device_local_context)


        # Step 5: Query and structure all interface metadata and assigned IP addresses for this device.
        interfaces = self._get_device_interfaces_and_ips(device_id)

        role_obj = device.get("role") or device.get("device_role") or {}
        role_slug = role_obj.get("slug") if isinstance(role_obj, dict) else (str(role_obj) if role_obj else None)

        platform_obj = device.get("platform") or {}
        platform_slug = platform_obj.get("slug") if isinstance(platform_obj, dict) else (str(platform_obj) if platform_obj else None)

        # Construct final unified context dictionary containing device info, merged config, and interfaces.
        # This dictionary is passed directly to ConfigGenerator to render deterministic CLI configuration.
        unified_context = {
            "device_info": {
                "id": device_id,
                "name": device_name,
                "site": site_slug,
                "role": role_slug,
                "platform": platform_slug,
                "primary_ip4": device.get("primary_ip4", {}).get("address") or device.get("primary_ip", {}).get("address")
            },
            "config": merged_config,
            "interfaces": interfaces
        }

        logger.info(f"Unified context completed for '{device_name}'. Merged configuration keys: {list(merged_config.keys())}")
        return unified_context

