"""
Purpose   : Protocol plugin generating Port Security CLI commands for access interfaces.
Consumes  : NetBox Config Context (`config.port_security`) and interface custom fields.
Produces  : Cisco IOS CLI (`switchport port-security`, `switchport port-security maximum ...`, `switchport port-security violation ...`).
"""

from typing import Any, List, Mapping, Optional, Sequence, Tuple


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError


logger = get_logger("PortSecurityProtocol")


class PortSecurityProtocol(BaseProtocol):
    """Render interface Port Security configuration from a device context.

    The plugin reads only the ``port_security`` interface custom field exposed
    by ``ContextBuilder`` and optional Port Security shutdown-recovery settings
    from the merged configuration context. It has no external I/O.
    """

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ``ConfigGenerator`` discovery."""
        return "port_security"

    @property
    def protocol_category(self) -> str:
        """Return functional protocol category."""
        return "LAYER2_SWITCHING"


    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains Port Security configuration."""
        global_settings = self._global_settings(device_context)
        if isinstance(global_settings, Mapping) and global_settings:
            return True

        return bool(self._interface_settings(device_context))

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate the Port Security settings required for CLI generation."""
        self._validate_shutdown_recovery(self._global_settings(device_context))

        for interface_name, settings, _ in self._interface_settings(device_context):
            self._validate_interface_settings(interface_name, settings)

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return Port Security CLI for configured interfaces and recovery."""
        configuration_lines = self._render_shutdown_recovery(
            self._global_settings(device_context)
        )
        interface_settings = self._interface_settings(device_context)

        for interface_name, settings, interface_data in interface_settings:
            interface_lines = self._render_interface_settings(
                interface_name, settings, interface_data
            )
            if interface_lines:
                configuration_lines.extend(interface_lines)

        logger.info(
            "Generated Port Security configuration for %d interface(s).",
            len(interface_settings),
        )
        return "\n".join(configuration_lines)

    @staticmethod
    def _global_settings(device_context: Mapping[str, Any]) -> Any:
        """Return only the Port Security portion of merged configuration."""
        configuration = device_context.get("config", {})
        if not isinstance(configuration, Mapping):
            return None
        return configuration.get("port_security") or configuration.get("port_security_policy")


    @staticmethod
    def _interface_settings(
        device_context: Mapping[str, Any],
    ) -> List[Tuple[Any, Any]]:
        """Extract only interface-level Port Security custom-field values."""
        interfaces = device_context.get("interfaces", {})
        if not isinstance(interfaces, Mapping):
            return []

        settings_by_interface: List[Tuple[Any, Any, Any]] = []
        for interface_name in sorted(interfaces, key=str):
            interface_data = interfaces[interface_name]
            if not isinstance(interface_data, Mapping):
                continue

            custom_fields = interface_data.get("custom_fields", {})
            if (
                isinstance(custom_fields, Mapping)
                and custom_fields.get("port_security") is not None
            ):
                settings_by_interface.append(
                    (interface_name, custom_fields["port_security"], interface_data)
                )

        return settings_by_interface

    def _validate_shutdown_recovery(self, global_settings: Any) -> None:
        """Validate optional device-wide Port Security recovery settings."""
        if global_settings is None:
            return
        if not isinstance(global_settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "global Port Security settings must be a mapping.",
            )

        shutdown_recovery = global_settings.get("shutdown_recovery")
        if shutdown_recovery is None:
            return
        if not isinstance(shutdown_recovery, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "shutdown recovery settings must be a mapping.",
            )

        if (
            "enabled" in shutdown_recovery
            and not isinstance(shutdown_recovery["enabled"], bool)
        ):
            raise ProtocolValidationError(
                self.protocol_name,
                "shutdown recovery enabled must be a boolean.",
            )

        if "interval" in shutdown_recovery:
            interval = shutdown_recovery["interval"]
            if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
                raise ProtocolValidationError(
                    self.protocol_name,
                    "shutdown recovery interval must be a positive integer.",
                )

    def _validate_interface_settings(self, interface_name: Any, settings: Any) -> None:
        """Validate one interface's Port Security configuration values."""
        if not isinstance(interface_name, str) or not interface_name.strip():
            raise ProtocolValidationError(
                self.protocol_name,
                "an interface with Port Security settings must have a valid name.",
            )
        if not isinstance(settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                f"Port Security settings for interface '{interface_name}' must be a mapping.",
            )

        for field_name in ("enabled", "sticky_mac"):
            if field_name in settings and not isinstance(settings[field_name], bool):
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"{field_name} for interface '{interface_name}' must be a boolean.",
                )

        for field_name in ("max_mac_addresses", "aging_time"):
            if field_name in settings:
                value = settings[field_name]
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ProtocolValidationError(
                        self.protocol_name,
                        f"{field_name} for interface '{interface_name}' must be a positive integer.",
                    )

        for field_name in ("violation", "aging_type"):
            if field_name in settings:
                self._validate_cli_text(settings[field_name], field_name, interface_name)

        if "secure_mac_addresses" in settings:
            secure_addresses = settings["secure_mac_addresses"]
            if isinstance(secure_addresses, str):
                self._validate_cli_text(
                    secure_addresses,
                    "secure_mac_addresses",
                    interface_name,
                )
            elif isinstance(secure_addresses, Sequence):
                for secure_address in secure_addresses:
                    self._validate_cli_text(
                        secure_address,
                        "secure_mac_addresses",
                        interface_name,
                    )
            else:
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"secure_mac_addresses for interface '{interface_name}' must be a string or sequence of strings.",
                )

    def _validate_cli_text(self, value: Any, field_name: str, interface_name: str) -> None:
        """Reject non-string or multiline values before forming CLI commands."""
        if (
            not isinstance(value, str)
            or not value.strip()
            or "\n" in value
            or "\r" in value
        ):
            raise ProtocolValidationError(
                self.protocol_name,
                f"{field_name} for interface '{interface_name}' must be a non-empty single-line string.",
            )

    def _render_shutdown_recovery(self, global_settings: Any) -> List[str]:
        """Render optional device-wide Port Security shutdown-recovery CLI."""
        if not isinstance(global_settings, Mapping):
            return []

        shutdown_recovery = global_settings.get("shutdown_recovery")
        if not isinstance(shutdown_recovery, Mapping):
            return []

        commands: List[str] = []
        if "enabled" in shutdown_recovery:
            command = "errdisable recovery cause psecure-violation"
            commands.append(command if shutdown_recovery["enabled"] else f"no {command}")
        if "interval" in shutdown_recovery:
            commands.append(
                f"errdisable recovery interval {shutdown_recovery['interval']}"
            )
        return commands

    @staticmethod
    def _render_interface_settings(
        interface_name: str,
        settings: Mapping[str, Any],
        interface_data: Optional[Mapping[str, Any]] = None,
    ) -> List[str]:
        """Render the CLI owned by one interface's Port Security settings."""
        commands: List[str] = []

        if settings.get("enabled"):
            mode = interface_data.get("mode") if isinstance(interface_data, Mapping) else None
            if mode is None or mode == "access":
                commands.append("switchport mode access")

        if "enabled" in settings:
            command = "switchport port-security"
            commands.append(command if settings["enabled"] else f"no {command}")
            if not settings["enabled"]:
                return [f"interface {interface_name}", *commands, "exit"]

        if "max_mac_addresses" in settings:
            commands.append(
                f"switchport port-security maximum {settings['max_mac_addresses']}"
            )
        if "violation" in settings:
            commands.append(f"switchport port-security violation {settings['violation']}")
        if "sticky_mac" in settings:
            command = "switchport port-security mac-address sticky"
            commands.append(command if settings["sticky_mac"] else f"no {command}")
        if "aging_time" in settings:
            commands.append(
                f"switchport port-security aging time {settings['aging_time']}"
            )
        if "aging_type" in settings:
            commands.append(
                f"switchport port-security aging type {settings['aging_type']}"
            )

        secure_addresses = settings.get("secure_mac_addresses", [])
        if isinstance(secure_addresses, str):
            secure_addresses = [secure_addresses]
        for secure_address in secure_addresses:
            commands.append(f"switchport port-security mac-address {secure_address}")

        return [f"interface {interface_name}", *commands, "exit"] if commands else []

