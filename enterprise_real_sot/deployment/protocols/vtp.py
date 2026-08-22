"""
Purpose   : Protocol plugin generating VLAN Trunking Protocol (VTP) domain and operating mode CLI commands.
Consumes  : NetBox Config Context (`config.vtp`).
Produces  : Cisco IOS CLI (`vtp mode transparent`, `vtp domain ...`).
"""

from typing import Any, List, Mapping


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("VtpProtocol")


class VtpProtocol(BaseProtocol):
    """Render VTP configuration from a device context.

    Reads global VTP configuration settings from ``device_context["config"]["vtp"]``.
    Supports VTP modes: off, transparent, client, server.
    """

    VALID_MODES = {"off", "transparent", "client", "server"}

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "vtp"

    @property
    def protocol_category(self) -> str:
        """Return functional protocol category."""
        return "LAYER2_SWITCHING"

    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains VTP configuration."""
        vtp_settings = self._get_vtp_settings(device_context)
        return isinstance(vtp_settings, Mapping) and bool(vtp_settings)



    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate VTP settings required for CLI generation."""
        vtp_settings = self._get_vtp_settings(device_context)
        if not isinstance(vtp_settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "global VTP settings must be a mapping.",
            )

        mode = vtp_settings.get("mode")
        if mode is not None:
            if not isinstance(mode, str) or not mode.strip():
                raise ProtocolValidationError(
                    self.protocol_name,
                    "VTP mode must be a non-empty string.",
                )
            if mode.strip().lower() not in self.VALID_MODES:
                valid_str = ", ".join(sorted(self.VALID_MODES))
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"invalid VTP mode '{mode}'. Must be one of: {valid_str}.",
                )

        for field_name in ("domain", "password"):
            if field_name in vtp_settings and vtp_settings[field_name] is not None:
                val = vtp_settings[field_name]
                if not isinstance(val, str) or not val.strip() or "\n" in val or "\r" in val:
                    raise ProtocolValidationError(
                        self.protocol_name,
                        f"VTP {field_name} must be a single-line non-empty string.",
                    )

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return VTP CLI configuration string."""
        vtp_settings = self._get_vtp_settings(device_context)
        if not isinstance(vtp_settings, Mapping):
            return ""

        commands: List[str] = []

        mode = vtp_settings.get("mode")
        if mode:
            commands.append(f"vtp mode {mode.strip().lower()}")

        domain = vtp_settings.get("domain")
        if domain:
            commands.append(f"vtp domain {domain.strip()}")

        password = vtp_settings.get("password")
        if password:
            commands.append(f"vtp password {password.strip()}")

        if commands:
            logger.info("Generated VTP configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_vtp_settings(device_context: Mapping[str, Any]) -> Any:
        """Extract VTP settings from device context config."""
        config = device_context.get("config", {})
        if not isinstance(config, Mapping):
            return None
        return config.get("vtp")
