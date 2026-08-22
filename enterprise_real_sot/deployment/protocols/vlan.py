"""
Purpose   : Protocol plugin generating VLAN database definitions and interface switchport mode (access/trunk) CLI commands.
Consumes  : NetBox Config Context (`config.vlans`) and Interfaces (`mode`, `untagged_vlan`, `tagged_vlans`).
Produces  : Cisco IOS CLI (`vlan <vid>`, `name <name>`, `switchport mode access`, `switchport access vlan <vid>`, `switchport trunk allowed vlan ...`).
"""

from typing import Any, List, Mapping, Optional, Sequence, Tuple, Union


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("VlanProtocol")


class VlanProtocol(BaseProtocol):
    """Render VLAN database and interface switchport mode/VLAN CLI commands.

    Reads global VLAN definitions from ``device_context["config"]["vlans"]`` and
    interface switchport mode/VLAN assignments from ``device_context["interfaces"]``.
    """

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "vlan"

    @property
    def protocol_category(self) -> str:
        """Return functional protocol category."""
        return "LAYER2_SWITCHING"


    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains VLAN configuration."""
        global_vlans = self._get_global_vlans(device_context)
        if isinstance(global_vlans, Sequence) and len(global_vlans) > 0:
            return True

        interfaces = self._get_interfaces(device_context)
        for _, interface_data in interfaces:
            mode = interface_data.get("mode")
            untagged = interface_data.get("untagged_vlan")
            tagged = interface_data.get("tagged_vlans")
            if mode or untagged is not None or (isinstance(tagged, Sequence) and len(tagged) > 0):
                return True

        return False

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate VLAN definitions and interface VLAN assignments."""
        global_vlans = self._get_global_vlans(device_context)
        if global_vlans is not None:
            if not isinstance(global_vlans, Sequence):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "global VLANs context must be a list/sequence.",
                )
            for vlan in global_vlans:
                self._validate_vlan_object(vlan)

        for interface_name, interface_data in self._get_interfaces(device_context):
            self._validate_interface_vlans(interface_name, interface_data)

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return global VLAN and interface switchport CLI configuration."""
        commands: List[str] = []

        # 1. Render Global VLAN Database commands
        global_vlans = self._get_global_vlans(device_context)
        if isinstance(global_vlans, Sequence):
            for vlan in sorted(global_vlans, key=lambda v: self._extract_vid(v) or 0):
                vid = self._extract_vid(vlan)
                if vid is None:
                    continue
                commands.append(f"vlan {vid}")
                name = vlan.get("name") if isinstance(vlan, Mapping) else None
                if isinstance(name, str) and name.strip():
                    commands.append(f" name {name.strip()}")

        # 2. Render Interface VLAN Assignment commands
        for interface_name, interface_data in self._get_interfaces(device_context):
            # Skip virtual interfaces (e.g. Vlan100) or non-switchport interfaces
            if self._is_virtual_interface(interface_name, interface_data):
                continue

            interface_cmds = self._render_interface_vlan(interface_name, interface_data)
            if interface_cmds:
                commands.extend(interface_cmds)

        if commands:
            logger.info("Generated VLAN configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_global_vlans(device_context: Mapping[str, Any]) -> Any:
        """Extract global VLAN definitions list from config context."""
        config = device_context.get("config", {})
        if isinstance(config, Mapping):
            vlans = config.get("vlans") or config.get("vlan_intent")
            if vlans is not None:
                return vlans
        return device_context.get("vlans") or device_context.get("vlan_intent")


    @staticmethod
    def _get_interfaces(device_context: Mapping[str, Any]) -> List[Tuple[str, Mapping[str, Any]]]:
        """Extract interface entries list from device context."""
        interfaces = device_context.get("interfaces", {})
        if not isinstance(interfaces, Mapping):
            return []

        result: List[Tuple[str, Mapping[str, Any]]] = []
        for interface_name in sorted(interfaces, key=str):
            data = interfaces[interface_name]
            if isinstance(data, Mapping):
                result.append((interface_name, data))
        return result

    @classmethod
    def _extract_vid(cls, vlan_item: Any) -> Optional[int]:
        """Extract integer VID from either integer value or dictionary."""
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

    def _validate_vlan_object(self, vlan_item: Any) -> None:
        """Validate single VLAN definition object."""
        vid = self._extract_vid(vlan_item)
        if vid is None or vid < 1 or vid > 4094:
            raise ProtocolValidationError(
                self.protocol_name,
                f"VLAN ID must be an integer between 1 and 4094. Got: {vlan_item}",
            )
        if isinstance(vlan_item, Mapping):
            name = vlan_item.get("name")
            if name is not None:
                if not isinstance(name, str) or "\n" in name or "\r" in name:
                    raise ProtocolValidationError(
                        self.protocol_name,
                        f"VLAN {vid} name must be a single-line string.",
                    )

    def _validate_interface_vlans(self, interface_name: str, interface_data: Mapping[str, Any]) -> None:
        """Validate VLAN parameters on an interface."""
        untagged = interface_data.get("untagged_vlan")
        if untagged is not None:
            vid = self._extract_vid(untagged)
            if vid is None or vid < 1 or vid > 4094:
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"untagged VLAN for interface '{interface_name}' must be between 1 and 4094.",
                )

        tagged = interface_data.get("tagged_vlans")
        if tagged is not None and not isinstance(tagged, Sequence):
            raise ProtocolValidationError(
                self.protocol_name,
                f"tagged VLANs for interface '{interface_name}' must be a list/sequence.",
            )
        if isinstance(tagged, Sequence):
            for t_vlan in tagged:
                vid = self._extract_vid(t_vlan)
                if vid is None or vid < 1 or vid > 4094:
                    raise ProtocolValidationError(
                        self.protocol_name,
                        f"tagged VLAN ID for interface '{interface_name}' must be between 1 and 4094.",
                    )

    @staticmethod
    def _is_virtual_interface(interface_name: str, interface_data: Mapping[str, Any]) -> bool:
        """Check if interface is a virtual SVI interface (e.g. Vlan100, Loopback0)."""
        if interface_name.lower().startswith("vlan") or interface_name.lower().startswith("loopback"):
            return True
        if interface_data.get("type") == "virtual":
            return True
        return False

    def _render_interface_vlan(self, interface_name: str, interface_data: Mapping[str, Any]) -> List[str]:
        """Render switchport mode and VLAN assignment CLI for one interface."""
        mode = interface_data.get("mode")
        untagged_vid = self._extract_vid(interface_data.get("untagged_vlan"))
        tagged_vlans = interface_data.get("tagged_vlans") or []

        tagged_vids = [
            vid for vid in (self._extract_vid(v) for v in tagged_vlans) if vid is not None
        ]

        commands: List[str] = []

        # Case 1: Access Mode (or default if mode is access / untagged_vlan present without tagged_vlans)
        if mode == "access" or (untagged_vid is not None and not tagged_vids and mode != "tagged"):
            commands.append("switchport mode access")
            if untagged_vid is not None:
                commands.append(f"switchport access vlan {untagged_vid}")

        # Case 2: Trunk Mode (mode is tagged/trunk or tagged_vids exist)
        elif mode in ("tagged", "trunk") or (tagged_vids and mode != "access"):
            commands.append("switchport trunk encapsulation dot1q")
            commands.append("switchport mode trunk")
            if untagged_vid is not None:
                commands.append(f"switchport trunk native vlan {untagged_vid}")
            if tagged_vids:
                vids_str = ",".join(str(v) for v in sorted(set(tagged_vids)))
                commands.append(f"switchport trunk allowed vlan {vids_str}")

        if not commands:
            return []

        return [f"interface {interface_name}", *commands, "exit"]
