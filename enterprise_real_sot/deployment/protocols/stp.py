"""
Purpose   : Protocol plugin generating Spanning Tree Protocol (STP) mode and PortFast/BPDU Guard CLI commands.
Consumes  : NetBox Config Context (`config.stp`).
Produces  : Cisco IOS CLI (`spanning-tree mode ...`, `spanning-tree portfast default`, `spanning-tree portfast bpduguard default`).
"""

from typing import Any, List, Mapping


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("StpProtocol")


class StpProtocol(BaseProtocol):
    """Render Spanning Tree Protocol (STP) CLI commands from device context."""

    VALID_MODES = {"pvst", "rapid-pvst", "mst"}

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "stp"

    @property
    def protocol_category(self) -> str:
        """Return functional protocol category."""
        return "LAYER2_SWITCHING"

    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains STP configuration."""
        settings = self._get_settings(device_context)
        return isinstance(settings, Mapping) and len(settings) > 0



    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate STP mode, priority, and default features."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "STP configuration settings must be a mapping.",
            )

        mode = settings.get("mode")
        if mode is not None:
            if not isinstance(mode, str) or mode.lower() not in self.VALID_MODES:
                valid_modes = ", ".join(sorted(self.VALID_MODES))
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"invalid STP mode '{mode}'. Must be one of: {valid_modes}.",
                )

        priority = settings.get("bridge_priority")
        if priority is not None:
            if isinstance(priority, bool) or not isinstance(priority, int) or priority < 0 or priority > 61440 or priority % 4096 != 0:
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"STP bridge priority must be an integer multiple of 4096 between 0 and 61440. Got: {priority}.",
                )

        for bool_field in ("portfast_default", "bpduguard_default", "loopguard_default"):
            if bool_field in settings and not isinstance(settings[bool_field], bool):
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"STP setting '{bool_field}' must be a boolean.",
                )

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return STP global CLI configuration string."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            return ""

        commands: List[str] = []

        mode = settings.get("mode")
        if mode:
            commands.append(f"spanning-tree mode {mode.lower()}")

        priority = settings.get("bridge_priority")
        if priority is not None:
            commands.append(f"spanning-tree priority {priority}")

        if settings.get("portfast_default") is True:
            commands.append("spanning-tree portfast default")
        elif settings.get("portfast_default") is False:
            commands.append("no spanning-tree portfast default")

        if settings.get("bpduguard_default") is True:
            commands.append("spanning-tree portfast bpduguard default")
        elif settings.get("bpduguard_default") is False:
            commands.append("no spanning-tree portfast bpduguard default")

        if settings.get("loopguard_default") is True:
            commands.append("spanning-tree loopguard default")
        elif settings.get("loopguard_default") is False:
            commands.append("no spanning-tree loopguard default")

        if commands:
            logger.info("Generated STP configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_settings(device_context: Mapping[str, Any]) -> Any:
        """Extract STP configuration dictionary from config context."""
        config = device_context.get("config", {})
        if not isinstance(config, Mapping):
            return None
        return config.get("stp")
