"""Network Time Protocol (NTP) compliance resource plugin."""

from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class NtpResource(BaseResource):
    """NTP compliance resource plugin.

    Extracts desired NTP source interface setting from NetBox context
    and parses read-only Cisco IOS 'show ntp status' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "ntp"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if device platform supports Cisco IOS NTP CLI."""
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
        """Determine whether NTP settings exist in NetBox config context."""
        config = device_context.get("config", {})
        return isinstance(config, Mapping) and isinstance(config.get("ntp"), Mapping)

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired NTP servers and source interface from NetBox config context."""
        config = device_context.get("config", {})
        ntp_data = config.get("ntp", {}) if isinstance(config, Mapping) else {}

        servers_raw = ntp_data.get("servers", [])
        servers: List[str] = []
        if isinstance(servers_raw, Sequence):
            for entry in servers_raw:
                if isinstance(entry, str) and entry.strip():
                    servers.append(entry.strip())
                elif isinstance(entry, Mapping):
                    addr = entry.get("address")
                    if isinstance(addr, str) and addr.strip():
                        servers.append(addr.strip())

        source_iface = str(ntp_data.get("source_interface", "")).strip()

        return {
            "servers": sorted(servers),
            "source_interface": source_iface,
        }

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only command to fetch NTP status and configuration on switch."""
        return ["show ntp status", "show running-config | include ntp"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show ntp status' and running-config output into actual NTP state."""
        raw_status = ""
        raw_run = ""
        if isinstance(raw_outputs, Mapping):
            for cmd_key, text in raw_outputs.items():
                key_norm = cmd_key.strip().lower()
                if "show ntp status" in key_norm:
                    raw_status = text
                elif "include ntp" in key_norm:
                    raw_run = text

        actual_servers: List[str] = []
        source_iface = ""

        for line in raw_run.splitlines():
            line_str = line.strip()
            line_lower = line_str.lower()
            if line_lower.startswith("ntp server"):
                parts = line_str.split()
                if len(parts) >= 3:
                    server_ip = parts[2]
                    if server_ip not in actual_servers:
                        actual_servers.append(server_ip)
            elif line_lower.startswith("ntp source"):
                parts = line_str.split()
                if len(parts) >= 3:
                    source_iface = parts[2]

        return {
            "servers": sorted(actual_servers),
            "source_interface": source_iface,
        }
