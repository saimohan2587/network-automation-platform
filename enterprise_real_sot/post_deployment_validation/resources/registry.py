"""Dynamic plugin discovery and registration for compliance resources."""

import importlib
import pkgutil
from typing import Any, Dict, List, Mapping, Optional, Sequence, Type

from post_deployment_validation.logger import get_logger
from post_deployment_validation.resources.base_resource import BaseResource

logger = get_logger("ResourceRegistry")


class ResourceRegistry:
    """Discovers, registers, and selects compliance resource plugins dynamically."""

    def __init__(self) -> None:
        self._plugins: Dict[str, BaseResource] = {}
        self._discover_plugins()

    def get_plugin(self, resource_name: str) -> Optional[BaseResource]:
        """Return registered plugin instance by resource name."""
        return self._plugins.get(resource_name)

    def get_all_plugins(self) -> List[BaseResource]:
        """Return all registered plugin instances."""
        return list(self._plugins.values())

    def get_applicable_resources(
        self,
        device_context: Mapping[str, Any],
        requested_protocols: Optional[Sequence[str]] = None,
    ) -> List[BaseResource]:
        """Return plugins that support the device and have desired state configured in NetBox."""
        applicable: List[BaseResource] = []

        # Determine target protocol filter set if requested by caller
        target_protocols = None
        if requested_protocols is not None and "all" not in [p.lower() for p in requested_protocols]:
            target_protocols = set(p.lower() for p in requested_protocols)

        for resource_name, plugin in self._plugins.items():
            if target_protocols and resource_name.lower() not in target_protocols:
                continue

            # Check 1: Plugin supports the device platform/vendor capability
            if not plugin.supports_device(device_context):
                logger.debug(
                    "Plugin '%s' does not support device platform.", resource_name
                )
                continue

            # Check 2: Plugin determines whether its desired state is configured in NetBox
            if not plugin.is_configured(device_context):
                logger.debug(
                    "Plugin '%s' is not configured for device in NetBox.", resource_name
                )
                continue

            applicable.append(plugin)

        return applicable

    def _discover_plugins(self) -> None:
        """Scan post_deployment_validation.resources package and register all BaseResource subclasses."""
        import post_deployment_validation.resources as resources_package

        package_path = resources_package.__path__
        package_prefix = resources_package.__name__ + "."

        for _, module_name, _ in pkgutil.iter_modules(package_path, package_prefix):
            try:
                module = importlib.import_module(module_name)
                for attribute_name in dir(module):
                    attribute = getattr(module, attribute_name)
                    if (
                        isinstance(attribute, type)
                        and issubclass(attribute, BaseResource)
                        and attribute is not BaseResource
                    ):
                        plugin_instance = attribute()
                        name = plugin_instance.resource_name
                        self._plugins[name] = plugin_instance
                        logger.debug(
                            "Discovered compliance resource plugin: '%s' (%s)",
                            name,
                            attribute_name,
                        )
            except Exception as error:
                logger.error("Failed to import resource module '%s': %s", module_name, error)
