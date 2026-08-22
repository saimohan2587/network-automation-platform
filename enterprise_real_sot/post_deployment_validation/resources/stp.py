"""Spanning Tree Protocol (STP) compliance resource plugin."""

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class StpResource(BaseResource):
    """STP compliance resource plugin.

    Extracts desired STP mode and default features from NetBox context
    and parses read-only Cisco IOS 'show spanning-tree summary' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "stp"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if device platform supports Cisco IOS STP CLI."""
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
        """Determine whether STP settings exist in NetBox config context."""
        config = device_context.get("config", {})
        return isinstance(config, Mapping) and isinstance(config.get("stp"), Mapping)

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired STP mode and PortFast/BPDU Guard default settings."""
        config = device_context.get("config", {})
        stp_data = config.get("stp", {}) if isinstance(config, Mapping) else {}

        mode = str(stp_data.get("mode", "rapid-pvst")).lower()
        bpduguard = bool(stp_data.get("bpduguard_default", False))
        portfast = bool(stp_data.get("portfast_default", False))


        return {
            "mode": mode,
            "bpduguard_default": bpduguard,
            "portfast_default": portfast,
        }

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only command to fetch STP summary on switch."""
        return ["show spanning-tree summary"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show spanning-tree summary' output into actual STP state."""
        raw_text = ""
        if isinstance(raw_outputs, Mapping):
            for cmd_key, text in raw_outputs.items():
                if cmd_key.strip().lower() == "show spanning-tree summary":
                    raw_text = text
                    break

        if "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            return {
                "mode": "unknown",
                "bpduguard_default": False,
                "portfast_default": False,
            }

        mode = "pvst"
        bpduguard = False
        portfast = False

        for line in raw_text.splitlines():
            line_lower = line.strip().lower()
            is_enabled = bool(re.search(r"\benabled\b", line_lower)) and "disabled" not in line_lower

            if "switch is in" in line_lower:
                if "rapid-pvst" in line_lower or "rstp" in line_lower:
                    mode = "rapid-pvst"
                elif "mst" in line_lower:
                    mode = "mst"
                elif "pvst" in line_lower:
                    mode = "pvst"
            elif "bpdu guard" in line_lower or "bpduguard" in line_lower:
                if is_enabled:
                    bpduguard = True
            elif "portfast" in line_lower:
                if ("enabled" in line_lower or "edge" in line_lower) and "disabled" not in line_lower:
                    portfast = True

        return {
            "mode": mode,
            "bpduguard_default": bpduguard,
            "portfast_default": portfast,
        }
