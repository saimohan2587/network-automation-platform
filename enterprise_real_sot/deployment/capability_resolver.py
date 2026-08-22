"""
Purpose   : Central Capability Resolver module for evaluating device role/platform capabilities.
Called By : deployment/config_generator.py (`ConfigGenerator.generate()`).
Calls Next: None (Pure classification & evaluation logic).
"""

from typing import Any, Mapping, Set
from deployment.logger import get_logger

logger = get_logger("CapabilityResolver")

# Protocol Category Constants
BASE_INTERFACE = "BASE_INTERFACE"
LAYER2_SWITCHING = "LAYER2_SWITCHING"
LAYER3_ROUTING = "LAYER3_ROUTING"
GLOBAL_MANAGEMENT = "GLOBAL_MANAGEMENT"

# Declarative Role-to-Capability Baseline Mapping
ROLE_CAPABILITY_MATRIX = {
    # Pure Layer 3 Gateway Routers
    "router": {BASE_INTERFACE, LAYER3_ROUTING, GLOBAL_MANAGEMENT},
    "l3-gateway-router": {BASE_INTERFACE, LAYER3_ROUTING, GLOBAL_MANAGEMENT},
    "border-router": {BASE_INTERFACE, LAYER3_ROUTING, GLOBAL_MANAGEMENT},

    # Pure Layer 2 Access Switches
    "access-switch": {BASE_INTERFACE, LAYER2_SWITCHING, GLOBAL_MANAGEMENT},
    "switch": {BASE_INTERFACE, LAYER2_SWITCHING, GLOBAL_MANAGEMENT},

    # Multi-Layer Switches (Distribution / Core switches with L2 switching + L3 routing capabilities)
    "distribution-switch": {BASE_INTERFACE, LAYER2_SWITCHING, LAYER3_ROUTING, GLOBAL_MANAGEMENT},
    "core-switch": {BASE_INTERFACE, LAYER2_SWITCHING, LAYER3_ROUTING, GLOBAL_MANAGEMENT},
    "multilayer-switch": {BASE_INTERFACE, LAYER2_SWITCHING, LAYER3_ROUTING, GLOBAL_MANAGEMENT},
}

# Safe Default Baseline for Unknown or Unmapped Device Roles
DEFAULT_CAPABILITY_BASELINE = {BASE_INTERFACE, GLOBAL_MANAGEMENT}


class CapabilityResolver:
    """Evaluates whether a device role/platform supports a protocol plugin category."""

    @classmethod
    def get_device_role(cls, device_context: Mapping[str, Any]) -> str:
        """Extract normalized device role string from unified device context."""
        device_info = device_context.get("device_info", {})
        if isinstance(device_info, Mapping):
            role = device_info.get("role") or device_info.get("device_role")
            if role:
                return str(role).strip().lower()

        # Fallback to top-level keys if device_info is unpopulated
        top_role = device_context.get("device_role") or device_context.get("role")
        if top_role:
            return str(top_role).strip().lower()

        return "unknown"

    @classmethod
    def get_supported_categories(cls, device_context: Mapping[str, Any]) -> Set[str]:
        """Return the set of supported protocol categories for the target device."""
        role = cls.get_device_role(device_context)

        # 1. Direct match in declarative role capability matrix
        if role in ROLE_CAPABILITY_MATRIX:
            return ROLE_CAPABILITY_MATRIX[role]

        # 2. Substring matching for role naming variations (e.g., 'cisco-router' -> 'router')
        if "router" in role:
            return ROLE_CAPABILITY_MATRIX["router"]
        if "access" in role or ("switch" in role and "dist" not in role and "core" not in role and "l3" not in role):
            return ROLE_CAPABILITY_MATRIX["access-switch"]
        if "dist" in role or "core" in role or "l3" in role:
            return ROLE_CAPABILITY_MATRIX["distribution-switch"]

        # 3. Safe fallback baseline for unknown roles with logging warning
        logger.warning(
            "Unknown device role '%s'; applying safe baseline capabilities (%s).",
            role,
            ", ".join(sorted(DEFAULT_CAPABILITY_BASELINE)),
        )
        return DEFAULT_CAPABILITY_BASELINE

    @classmethod
    def is_supported(cls, plugin: Any, device_context: Mapping[str, Any]) -> bool:
        """Determine if a protocol plugin category is supported by the device capability gate."""
        category = getattr(plugin, "protocol_category", GLOBAL_MANAGEMENT)
        supported_categories = cls.get_supported_categories(device_context)

        if category not in supported_categories:
            role = cls.get_device_role(device_context)
            logger.info(
                "Skipping protocol '%s': unsupported for device role '%s'.",
                getattr(plugin, "protocol_name", str(plugin)),
                role,
            )
            return False

        return True
