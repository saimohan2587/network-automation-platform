"""Interface Base compliance resource plugin."""

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class InterfaceBaseResource(BaseResource):
    """Interface Base compliance resource plugin.

    Extracts desired interface administrative state and descriptions from NetBox
    and parses read-only Cisco IOS 'show interfaces status' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "interface_base"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if the device platform supports Cisco IOS interface CLI."""
        platform = device_context.get("platform", {})
        if isinstance(platform, Mapping):
            slug = platform.get("slug", "").replace("-", "_").lower()
            if slug in ("cisco_ios", "cisco_xe", "cisco_ios_xe"):
                return True

        device_type = device_context.get("device_type", {})
        if isinstance(device_type, Mapping):
            manufacturer = device_type.get("manufacturer", {})
            if isinstance(manufacturer, Mapping) and manufacturer.get("slug") == "cisco":
                return True

        return True

    def is_configured(self, device_context: Mapping[str, Any]) -> bool:
        """Determine whether interfaces are defined in NetBox context."""
        interfaces = device_context.get("interfaces", {})
        return isinstance(interfaces, Mapping) and len(interfaces) > 0

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired interface enabled state and description from NetBox context."""
        interfaces = device_context.get("interfaces", {})
        if not isinstance(interfaces, Mapping):
            return {"interfaces": {}}

        target_interfaces = None
        if requested_interfaces is not None and "all" not in [i.lower() for i in requested_interfaces]:
            target_interfaces = set(requested_interfaces)

        desired_interfaces: Dict[str, Any] = {}
        for iface_name in sorted(interfaces, key=str):
            if target_interfaces and iface_name not in target_interfaces:
                continue

            iface_data = interfaces[iface_name]
            if not isinstance(iface_data, Mapping):
                continue

            # Skip virtual / loopback / SVI interfaces
            if iface_name.lower().startswith("vlan") or iface_name.lower().startswith("loopback"):
                continue

            enabled = bool(iface_data.get("enabled", True))
            description = str(iface_data.get("description") or "").strip()

            desired_interfaces[iface_name] = {
                "enabled": enabled,
                "description": description,
            }

        return {"interfaces": desired_interfaces}

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only commands to fetch interface status and descriptions on switch."""
        return ["show interfaces status", "show interfaces description"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show interfaces status' and 'show interfaces description' outputs into normalized actual state map."""
        raw_status = ""
        raw_desc = ""
        if isinstance(raw_outputs, Mapping):
            for cmd_key, text in raw_outputs.items():
                key_norm = cmd_key.strip().lower()
                if key_norm == "show interfaces status":
                    raw_status = text
                elif key_norm == "show interfaces description":
                    raw_desc = text

        desired_interfaces = desired_state.get("interfaces", {})

        actual_map = self._parse_show_interfaces_status(raw_status)
        desc_map = self._parse_show_interfaces_description(raw_desc)

        # Merge untruncated descriptions from show interfaces description
        for port_name, desc_info in desc_map.items():
            if port_name in actual_map:
                if isinstance(desc_info, dict):
                    actual_map[port_name]["description"] = desc_info.get("description", "")
                else:
                    actual_map[port_name]["description"] = str(desc_info)

        actual_interfaces: Dict[str, Any] = {}
        for iface_name in desired_interfaces:
            parsed_data = self._lookup_interface_data(iface_name, actual_map, desc_map)
            actual_interfaces[iface_name] = parsed_data

        return {"interfaces": actual_interfaces}

    @classmethod
    def _parse_show_interfaces_status(cls, raw_text: str) -> Dict[str, Dict[str, Any]]:
        """Parse lines from 'show interfaces status' output."""
        parsed: Dict[str, Dict[str, Any]] = {}

        if "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            return parsed

        for line in raw_text.splitlines():
            line_str = line.rstrip()
            if not line_str or line_str.startswith("Port") or line_str.startswith("-"):
                continue

            parts = line_str.split()
            if len(parts) >= 2:
                port_name = parts[0]
                canon_name = cls._canonical_interface_name(port_name)

                # Check status tokens specifically (connected, notconnect, disabled, err-disabled)
                # rather than checking the whole line string which might contain 'disabled' in description
                status_token = ""
                for token in parts[1:]:
                    token_lower = token.lower()
                    if token_lower in ("connected", "notconnect", "disabled", "err-disabled", "inactive"):
                        status_token = token_lower
                        break

                enabled = status_token != "disabled"

                entry = {
                    "enabled": enabled,
                    "description": "",
                }
                parsed[port_name] = entry
                if canon_name and canon_name != port_name:
                    parsed[canon_name] = entry

        return parsed

    @classmethod
    def _parse_show_interfaces_description(cls, raw_text: str) -> Dict[str, Any]:
        """Parse lines from 'show interfaces description' output for full untruncated descriptions."""
        parsed_descriptions: Dict[str, Any] = {}

        if "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            return parsed_descriptions

        pattern = re.compile(r"^(\S+)\s+(up|down|admin down)\s+(up|down)(?:\s+(.*))?$", re.IGNORECASE)

        for line in raw_text.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("Interface") or line_str.startswith("-"):
                continue

            match = pattern.match(line_str)
            if match:
                port_name = match.group(1)
                canon_name = cls._canonical_interface_name(port_name)
                status_str = match.group(2).lower()
                enabled = status_str != "admin down"
                desc = (match.group(4) or "").strip()
                desc_entry = {"enabled": enabled, "description": desc}
                parsed_descriptions[port_name] = desc_entry
                if canon_name and canon_name != port_name:
                    parsed_descriptions[canon_name] = desc_entry

        return parsed_descriptions

    @classmethod
    def _lookup_interface_data(
        cls,
        iface_name: str,
        actual_map: Dict[str, Dict[str, Any]],
        desc_map: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Look up parsed interface entry handling short name abbreviations, canonical names, and case variations."""
        target_entry = None
        target_desc = None

        canon_iface_name = cls._canonical_interface_name(iface_name)

        if iface_name in actual_map:
            target_entry = actual_map[iface_name]
        elif canon_iface_name in actual_map:
            target_entry = actual_map[canon_iface_name]

        abbrev = cls._abbreviate_interface_name(iface_name)
        if target_entry is None and abbrev in actual_map:
            target_entry = actual_map[abbrev]

        target_norm = iface_name.lower().replace(" ", "")
        canon_norm = canon_iface_name.lower().replace(" ", "")
        abbrev_norm = abbrev.lower().replace(" ", "")

        if target_entry is None:
            for key, val in actual_map.items():
                key_norm = key.lower().replace(" ", "")
                if key_norm in (target_norm, canon_norm, abbrev_norm):
                    target_entry = val
                    break

        if iface_name in desc_map:
            target_desc = desc_map[iface_name]
        elif canon_iface_name in desc_map:
            target_desc = desc_map[canon_iface_name]
        elif abbrev in desc_map:
            target_desc = desc_map[abbrev]
        else:
            for key, val in desc_map.items():
                key_norm = key.lower().replace(" ", "")
                if key_norm in (target_norm, canon_norm, abbrev_norm):
                    target_desc = val
                    break

        if target_entry is not None:
            entry = dict(target_entry)
            if target_desc is not None:
                if isinstance(target_desc, dict):
                    entry["description"] = target_desc.get("description", "")
                else:
                    entry["description"] = str(target_desc)
            return entry

        if target_desc is not None:
            if isinstance(target_desc, dict):
                return dict(target_desc)
            return {"enabled": True, "description": str(target_desc)}

        return {
            "enabled": "N/A (Interface Missing on Switch)",
            "description": "N/A",
        }

    @classmethod
    def _canonical_interface_name(cls, name: str) -> str:
        """Convert abbreviated or variant Cisco interface name to canonical full name."""
        if not name or not isinstance(name, str):
            return ""
        s = name.strip()

        prefix_mappings = [
            ("TenGigabitEthernet", "TenGigabitEthernet"),
            ("TenGigE", "TenGigabitEthernet"),
            ("Te", "TenGigabitEthernet"),
            ("TwentyFiveGigE", "TwentyFiveGigE"),
            ("TwentyFiveGig", "TwentyFiveGigE"),
            ("Twe", "TwentyFiveGigE"),
            ("FortyGigabitEthernet", "FortyGigabitEthernet"),
            ("FortyGigE", "FortyGigabitEthernet"),
            ("Fo", "FortyGigabitEthernet"),
            ("HundredGigE", "HundredGigE"),
            ("Hu", "HundredGigE"),
            ("GigabitEthernet", "GigabitEthernet"),
            ("GigE", "GigabitEthernet"),
            ("Gig", "GigabitEthernet"),
            ("Gi", "GigabitEthernet"),
            ("FastEthernet", "FastEthernet"),
            ("FastEth", "FastEthernet"),
            ("Fa", "FastEthernet"),
            ("Port-channel", "Port-channel"),
            ("Port-Channel", "Port-channel"),
            ("Po", "Port-channel"),
            ("Ethernet", "Ethernet"),
            ("Eth", "Ethernet"),
        ]

        for short, full in prefix_mappings:
            pattern = rf"^{re.escape(short)}\s*(\d.*)$"
            match = re.match(pattern, s, re.IGNORECASE)
            if match:
                return f"{full}{match.group(1)}"

        return s

    @staticmethod
    def _abbreviate_interface_name(name: str) -> str:
        """Convert full Cisco interface name to standard abbreviation."""
        mapping = [
            ("TenGigabitEthernet", "Te"),
            ("GigabitEthernet", "Gi"),
            ("FastEthernet", "Fa"),
            ("Ethernet", "Eth"),
            ("Port-channel", "Po"),
        ]
        for full, short in mapping:
            if name.startswith(full):
                return name.replace(full, short, 1)
        return name
