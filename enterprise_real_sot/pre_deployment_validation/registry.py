"""Dynamic plugin discovery and registration for pre-deployment validators."""

import importlib
import logging
import pkgutil
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pre_deployment_validation.base_validator import BaseProtocolValidator

logger = logging.getLogger("ValidatorRegistry")


class ValidatorRegistry:
    """Discovers, registers, and selects pre-deployment validator plugins dynamically."""

    def __init__(self) -> None:
        self._plugins: Dict[str, BaseProtocolValidator] = {}
        self._discover_plugins()

    def get_plugin(self, validator_name: str) -> Optional[BaseProtocolValidator]:
        """Return registered validator instance by name."""
        return self._plugins.get(validator_name)

    def get_all_plugins(self) -> List[BaseProtocolValidator]:
        """Return all registered validator instances sorted by priority."""
        return sorted(list(self._plugins.values()), key=lambda p: p.priority)

    def get_applicable_validators(
        self,
        device_context: Mapping[str, Any],
        requested_protocols: Optional[Sequence[str]] = None,
    ) -> List[BaseProtocolValidator]:
        """Return plugins that support the device and have configuration intent in NetBox.

        Results are sorted deterministically by validator priority.
        """
        applicable: List[BaseProtocolValidator] = []

        target_protocols = None
        if requested_protocols is not None and "all" not in [
            p.lower() for p in requested_protocols
        ]:
            target_protocols = set(p.lower() for p in requested_protocols)

        for validator_name, plugin in self._plugins.items():
            if target_protocols and validator_name.lower() not in target_protocols:
                continue

            if not plugin.supports_device(device_context):
                logger.debug(
                    "Validator '%s' does not support device platform.", validator_name
                )
                continue

            if not plugin.is_configured(device_context):
                logger.debug(
                    "Validator '%s' is not configured for device in NetBox context.",
                    validator_name,
                )
                continue

            applicable.append(plugin)

        # Sort applicable validators deterministically by priority (lower numbers execute earlier)
        applicable.sort(key=lambda p: p.priority)
        return applicable

    def _discover_plugins(self) -> None:
        """Scan pre_deployment_validation.validators package and register all BaseProtocolValidator subclasses."""
        import pre_deployment_validation.validators as validators_package

        package_path = validators_package.__path__
        package_prefix = validators_package.__name__ + "."

        for _, module_name, _ in pkgutil.iter_modules(package_path, package_prefix):
            try:
                module = importlib.import_module(module_name)
                for attribute_name in dir(module):
                    attribute = getattr(module, attribute_name)
                    if (
                        isinstance(attribute, type)
                        and issubclass(attribute, BaseProtocolValidator)
                        and attribute is not BaseProtocolValidator
                    ):
                        plugin_instance = attribute()
                        name = plugin_instance.validator_name
                        self._plugins[name] = plugin_instance
                        logger.debug(
                            "Discovered pre-deployment validator plugin: '%s' (%s, priority=%d)",
                            name,
                            attribute_name,
                            plugin_instance.priority,
                        )
            except Exception as error:
                logger.error(
                    "Failed to import validator module '%s': %s", module_name, error
                )
