import copy
import logging

logger = logging.getLogger("NetBoxImporter")

class MergeEngine:
    def __init__(self):
        pass

    def deep_merge(self, dict1, dict2):
        """
        Recursively merges dict2 into dict1.
        Modifies dict1 in-place.
        """
        for key, value in dict2.items():
            if key in dict1:
                if isinstance(dict1[key], dict) and isinstance(value, dict):
                    self.deep_merge(dict1[key], value)
                elif isinstance(dict1[key], list) and isinstance(value, list):
                    # For simple lists (like DNS IP servers), overwrite or combine uniquely
                    if all(not isinstance(i, dict) for i in dict1[key] + value):
                        dict1[key] = list(dict(zip(dict1[key] + value, dict1[key] + value)).keys())
                    else:
                        # If list of dicts, it will be handled at the resource merging step
                        dict1[key] = copy.deepcopy(value)
                else:
                    dict1[key] = copy.deepcopy(value)
            else:
                dict1[key] = copy.deepcopy(value)
        return dict1

    def merge_list_of_dicts(self, list1, list2, identifier_key):
        """
        Merges two lists of dicts based on a common key (e.g. 'name', 'vid', 'prefix').
        If elements match, deep merges them.
        """
        merged_map = {}
        
        for item in list1:
            if isinstance(item, dict) and identifier_key in item:
                merged_map[item[identifier_key]] = copy.deepcopy(item)
                
        for item in list2:
            if isinstance(item, dict) and identifier_key in item:
                key_val = item[identifier_key]
                if key_val in merged_map:
                    self.deep_merge(merged_map[key_val], item)
                else:
                    merged_map[key_val] = copy.deepcopy(item)
                    
        return list(merged_map.values())

    def merge(self, global_cfg, site_cfg, device_cfg):
        """
        Executes hierarchical merge:
        Global -> Site -> Device

        Returns a single unified dictionary representing the device config.
        """
        # Start with a deep copy of Global
        merged = copy.deepcopy(global_cfg)

        # 1. Merge Site configuration into the copy of Global
        # Extract site metadata block (don't override the SNMP contact info, etc., but merge dicts)
        site_meta = site_cfg.get("site", {})
        self.deep_merge(merged, {k: v for k, v in site_cfg.items() if k != "site"})

        # 2. Extract Device sections from device_cfg
        device_meta = device_cfg.get("device", {})
        device_mgmt = device_cfg.get("management", {})

        # Merge device local dictionaries into global + site settings
        for key, value in device_cfg.items():
            if key not in ["device", "management", "interfaces", "vlans"]:
                if isinstance(value, dict):
                    if key in merged and isinstance(merged[key], dict):
                        self.deep_merge(merged[key], value)
                    else:
                        merged[key] = copy.deepcopy(value)
                else:
                    merged[key] = copy.deepcopy(value)

        # 3. Perform smart list merges for interfaces, vlans, prefixes, racks, locations
        site_vlans = site_cfg.get("vlans", [])
        device_vlans = device_cfg.get("vlans", [])
        # Merge VLANs using 'vid' as the identifier
        merged["vlans"] = self.merge_list_of_dicts(site_vlans, device_vlans, "vid")

        site_prefixes = site_cfg.get("prefixes", [])
        # Prefixes typically defined only at Site level, but support overrides/device level if defined
        device_prefixes = device_cfg.get("prefixes", [])
        merged["prefixes"] = self.merge_list_of_dicts(site_prefixes, device_prefixes, "prefix")

        # Interfaces are device specific but we support list representation
        device_interfaces = device_cfg.get("interfaces", [])
        merged["interfaces"] = self.merge_list_of_dicts([], device_interfaces, "name")

        # Pass locations and racks through
        merged["locations"] = copy.deepcopy(site_cfg.get("locations", []))
        merged["racks"] = copy.deepcopy(site_cfg.get("racks", []))

        # 4. Flatten metadata fields directly to the root for ease of access
        # Host/Device properties
        for k, v in device_meta.items():
            merged[k] = v

        # Management configurations
        for k, v in device_mgmt.items():
            merged[k] = v

        # Add site slug directly
        if "slug" in site_meta:
            merged["site_slug"] = site_meta["slug"]

        # Reconstruct legacy top-level dicts for absolute backward compatibility
        # Reconstruct port_security
        port_sec_interfaces = {}
        for intf in merged.get("interfaces", []):
            if "port_security" in intf:
                port_sec_interfaces[intf["name"]] = copy.deepcopy(intf["port_security"])
        if port_sec_interfaces:
            if "port_security" not in merged:
                merged["port_security"] = {}
            if "interfaces" not in merged["port_security"]:
                merged["port_security"]["interfaces"] = {}
            self.deep_merge(merged["port_security"]["interfaces"], port_sec_interfaces)

        # Reconstruct ipv6.interfaces
        ipv6_interfaces = {}
        for intf in merged.get("interfaces", []):
            if "ipv6" in intf:
                ipv6_interfaces[intf["name"]] = copy.deepcopy(intf["ipv6"])
        if ipv6_interfaces:
            if "ipv6" not in merged:
                merged["ipv6"] = {}
            if "interfaces" not in merged["ipv6"]:
                merged["ipv6"]["interfaces"] = {}
            self.deep_merge(merged["ipv6"]["interfaces"], ipv6_interfaces)

        return merged

