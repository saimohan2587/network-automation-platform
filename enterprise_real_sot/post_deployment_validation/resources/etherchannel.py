"""EtherChannel compliance resource plugin."""

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from post_deployment_validation.resources.base_resource import BaseResource


class EtherChannelResource(BaseResource):
    """EtherChannel compliance resource plugin.

    Extracts desired channel-group assignments from NetBox context
    and parses read-only Cisco IOS 'show etherchannel summary' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "etherchannel"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if the device platform supports Cisco IOS EtherChannel CLI."""
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
        """Determine whether EtherChannel / LAG settings are defined in NetBox context."""
        config = device_context.get("config", {})
        if isinstance(config, Mapping) and isinstance(config.get("etherchannel"), Mapping):
            return True

        interfaces = device_context.get("interfaces", {})
        if isinstance(interfaces, Mapping):
            for iface_data in interfaces.values():
                if isinstance(iface_data, Mapping) and iface_data.get("lag"):
                    return True

        return False

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired channel-group ID and mode for member interfaces from NetBox context."""
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

            lag = iface_data.get("lag")
            if not lag:
                continue

            group_id = None
            mode = "active"

            if isinstance(lag, int):
                group_id = lag
            elif isinstance(lag, str):
                digits = "".join(c for c in lag if c.isdigit())
                if digits:
                    group_id = int(digits)
            elif isinstance(lag, Mapping):
                name = str(lag.get("name", ""))
                digits = "".join(c for c in name if c.isdigit())
                if digits:
                    group_id = int(digits)
                mode = str(lag.get("mode", "active")).lower()

            if group_id is not None:
                desired_interfaces[iface_name] = {
                    "channel_group": group_id,
                    "mode": mode,
                }

        return {"interfaces": desired_interfaces}

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only command to fetch EtherChannel summary on switch."""
        return ["show etherchannel summary"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show etherchannel summary' output into normalized actual state map."""
        raw_text = raw_outputs.get("show etherchannel summary", "")
        desired_interfaces = desired_state.get("interfaces", {})

        actual_map = self._parse_show_etherchannel_summary(raw_text)

        actual_interfaces: Dict[str, Any] = {}
        for iface_name in desired_interfaces:
            parsed_data = self._lookup_interface_data(iface_name, actual_map)
            actual_interfaces[iface_name] = parsed_data

        return {"interfaces": actual_interfaces}

    @classmethod
    def _parse_show_etherchannel_summary(cls, raw_text: str) -> Dict[str, Dict[str, Any]]:
        """Parse member interface assignments from 'show etherchannel summary' output."""
        parsed: Dict[str, Dict[str, Any]] = {}

        if "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            return parsed

        # Search for lines containing Group, Port-channel, Protocol, Ports
        # Example format: 1  Po1(SU)  LACP  Gi3/0/1(P) Gi3/0/2(P)
        for line in raw_text.splitlines():
            line_str = line.strip()
            if not line_str or not line_str[0].isdigit():
                continue

            parts = line_str.split()
            if len(parts) >= 4:
                try:
                    group_id = int(parts[0])
                    protocol_str = parts[2].lower()
                    mode = "active" if "lacp" in protocol_str else "on"

                    # Remaining elements are member ports (e.g. Gi3/0/1(P), Gi3/0/2(P))
                    for port_token in parts[3:]:
                        # Remove flags in parentheses (e.g., Gi3/0/1(P) -> Gi3/0/1)
                        port_name = re.sub(r"\(.*?\)", "", port_token).strip()
                        if port_name:
                            parsed[port_name] = {
                                "channel_group": group_id,
                                "mode": mode,
                            }
                except ValueError:
                    continue

        return parsed

    @classmethod
    def _lookup_interface_data(cls, iface_name: str, actual_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Look up interface channel-group membership by full or short name."""
        if iface_name in actual_map:
            return actual_map[iface_name]

        abbrev = cls._abbreviate_interface_name(iface_name)
        if abbrev in actual_map:
            return actual_map[abbrev]

        return {
            "channel_group": 0,
            "mode": "none",
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
