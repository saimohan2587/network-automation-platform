"""VLAN compliance resource plugin."""

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class VlanResource(BaseResource):
    """VLAN compliance resource plugin.

    Extracts desired VLAN assignments and switchport modes from NetBox context
    and parses read-only Cisco IOS 'show interfaces switchport' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "vlan"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if the device platform supports Cisco IOS switchport CLI."""
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
        """Determine whether VLAN settings are defined in NetBox context."""
        interfaces = device_context.get("interfaces", {})
        if not isinstance(interfaces, Mapping):
            return False

        for iface_data in interfaces.values():
            if isinstance(iface_data, Mapping):
                if (
                    iface_data.get("mode")
                    or iface_data.get("untagged_vlan") is not None
                    or iface_data.get("tagged_vlans")
                ):
                    return True
        return False

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired switchport mode and access/native VLAN IDs from NetBox context."""
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

            # Skip virtual interfaces / SVI
            if iface_name.lower().startswith("vlan") or iface_name.lower().startswith("loopback"):
                continue

            raw_mode = iface_data.get("mode")
            untagged = self._extract_vid(iface_data.get("untagged_vlan"))
            tagged_vlans = iface_data.get("tagged_vlans") or []

            # Determine expected operational mode
            if raw_mode in ("tagged", "trunk") or (tagged_vlans and raw_mode != "access"):
                native_vlan = untagged if untagged is not None else 1
                desired_interfaces[iface_name] = {
                    "mode": "trunk",
                    "native_vlan": native_vlan,
                }
            else:
                access_vlan = untagged if untagged is not None else 1
                desired_interfaces[iface_name] = {
                    "mode": "access",
                    "access_vlan": access_vlan,
                }

        return {"interfaces": desired_interfaces}

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only command to fetch interface switchport parameters."""
        return ["show interfaces switchport"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show interfaces switchport' output into normalized actual state map."""
        raw_text = ""
        if isinstance(raw_outputs, Mapping):
            for cmd_key, text in raw_outputs.items():
                if cmd_key.strip().lower() == "show interfaces switchport":
                    raw_text = text
                    break

        desired_interfaces = desired_state.get("interfaces", {})

        actual_map = self._parse_show_interfaces_switchport(raw_text)

        actual_interfaces: Dict[str, Any] = {}
        for iface_name, desired_spec in desired_interfaces.items():
            parsed_data = self._lookup_interface_data(iface_name, actual_map)
            # Filter actual fields to match only what desired_state expects for this interface mode
            filtered_actual = {}
            for field in desired_spec:
                if field in parsed_data:
                    filtered_actual[field] = parsed_data[field]
                else:
                    filtered_actual[field] = "N/A"
            actual_interfaces[iface_name] = filtered_actual

        return {"interfaces": actual_interfaces}

    @classmethod
    def _parse_show_interfaces_switchport(cls, raw_text: str) -> Dict[str, Dict[str, Any]]:
        """Parse blocks from 'show interfaces switchport' output."""
        parsed: Dict[str, Dict[str, Any]] = {}

        if "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            return parsed

        # Split output into interface blocks starting with Name:
        blocks = raw_text.split("Name: ")
        for block in blocks:
            if not block.strip():
                continue

            lines = block.splitlines()
            ifname_raw = lines[0].strip()

            mode = "access"
            access_vlan = 1
            native_vlan = 1

            native_vlan_parsed = False

            for line in lines[1:]:
                line_str = line.strip()
                if ":" not in line_str:
                    continue

                key, value = [part.strip() for part in line_str.split(":", 1)]
                key_lower = key.lower()

                if "administrative mode" in key_lower:
                    if "trunk" in value.lower():
                        mode = "trunk"
                    elif "access" in value.lower():
                        mode = "access"
                elif key_lower == "access mode vlan":
                    vid = cls._extract_vid_from_string(value)
                    if vid is not None:
                        access_vlan = vid
                elif key_lower == "trunking native mode vlan":
                    vid = cls._extract_vid_from_string(value)
                    if vid is not None:
                        native_vlan = vid
                        native_vlan_parsed = True

            parsed[ifname_raw] = {
                "mode": mode,
                "access_vlan": access_vlan,
                "native_vlan": native_vlan,
                "_native_vlan_parsed": native_vlan_parsed,
            }

        # Secondary pass: For trunk ports where native_vlan was not explicitly printed
        # in the CLI output (e.g. member interfaces of a Port-channel bundle like Te3/1/1),
        # inherit native_vlan from any parsed Port-channel interface.
        po_native_vlan = None
        for k, v in parsed.items():
            if (k.startswith("Po") or "Port-channel" in k) and v.get("_native_vlan_parsed"):
                po_native_vlan = v.get("native_vlan")
                break

        if po_native_vlan is not None:
            for k, v in parsed.items():
                if v.get("mode") == "trunk" and not v.get("_native_vlan_parsed"):
                    v["native_vlan"] = po_native_vlan

        return parsed

    @staticmethod
    def _extract_vid_from_string(val_str: str) -> Optional[int]:
        """Extract numeric VLAN ID from string like '10 (VLAN0010)' or '1'."""
        match = re.search(r"^(\d+)", val_str.strip())
        if match:
            return int(match.group(1))
        return None

    @classmethod
    def _extract_vid(cls, vlan_item: Any) -> Optional[int]:
        """Extract integer VID from integer or dict."""
        if isinstance(vlan_item, bool):
            return None
        if isinstance(vlan_item, int):
            return vlan_item
        if isinstance(vlan_item, Mapping):
            vid = vlan_item.get("vid")
            if isinstance(vid, int) and not isinstance(vid, bool):
                return vid
            if isinstance(vid, str) and vid.isdigit():
                return int(vid)
        return None

    @classmethod
    def _lookup_interface_data(cls, iface_name: str, actual_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Look up interface entry with full, short, and case-insensitive name matching."""
        if iface_name in actual_map:
            return actual_map[iface_name]

        abbrev = cls._abbreviate_interface_name(iface_name)
        if abbrev in actual_map:
            return actual_map[abbrev]

        target_norm = iface_name.lower().replace(" ", "")
        abbrev_norm = abbrev.lower().replace(" ", "")

        for key, val in actual_map.items():
            key_norm = key.lower().replace(" ", "")
            if key_norm == target_norm or key_norm == abbrev_norm:
                return val

        return {
            "mode": "N/A (Interface Missing on Switch)",
            "access_vlan": "N/A",
            "native_vlan": "N/A",
        }

    @staticmethod
    def _abbreviate_interface_name(name: str) -> str:
        """Convert full Cisco interface name to standard abbreviation."""
        mapping = [
            ("GigabitEthernet", "Gi"),
            ("TenGigabitEthernet", "Te"),
            ("FastEthernet", "Fa"),
            ("Ethernet", "Eth"),
            ("Port-channel", "Po"),
        ]
        for full, short in mapping:
            if name.startswith(full):
                return name.replace(full, short, 1)
        return name
