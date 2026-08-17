"""
Purpose   : Discovers protocol plugins and feeds unified device context into them to render Cisco CLI commands.
Called By : main.py (`DeploymentOrchestrator._assess_device()`).
Calls Next: deployment/protocols/*.py (`render()`), then returns CLI commands to main.py.
"""

import importlib
import inspect
import pkgutil
from typing import Any, Dict, List, Mapping, Optional, Sequence, Type


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError


logger = get_logger("ConfigGenerator")

# Defines the Python package path where protocol plugin files reside.
# If plugins are moved to another folder tomorrow, updating this single line keeps discovery working.
PROTOCOL_PACKAGE = "deployment.protocols"


# Custom exception raised when CLI generation fails due to invalid context or rendering errors.
# Callers like main.py catch this to distinguish generator errors from network SSH errors.
class ConfigGenerationError(RuntimeError):
    """Raised when configuration cannot be generated from protocol plugins."""


# Raised when dynamic plugin discovery fails (e.g., broken plugin module file).
# Inherits from ConfigGenerationError so callers can catch all generation issues in one try-block.
class ProtocolDiscoveryError(ConfigGenerationError):
    """Raised when a protocol plugin cannot be discovered or initialized."""


PREFERRED_PROTOCOL_ORDER = [
    "interface_base",
    "vlan",
    "etherchannel",
    "port_security",
    "stp",
    "vtp",
    "dhcp_snooping",
    "cdp",
    "lldp",
    "dns",
    "ntp",
    "syslog",
    "snmp",
    "aaa",
    "ipv6",
]


class ConfigGenerator:
    """Generate configuration by coordinating independent protocol plugins.

    The generator receives a unified device context and delegates all
    protocol-specific work to concrete :class:`BaseProtocol` implementations.
    It does not access NetBox, select devices, establish connections, or render
    vendor-specific configuration itself.
    """

    def discover_plugins(self) -> Dict[str, BaseProtocol]:
        """Discover and instantiate concrete protocol plugins in the package.

        Returns:
            A mapping of each plugin's declared protocol name to its instance.

        Raises:
            ProtocolDiscoveryError: If a plugin module cannot be loaded, a
                concrete plugin cannot be initialized, or duplicate/invalid
                protocol metadata is discovered.
        """
        try:
            # Dynamically import the protocols package at runtime instead of hardcoding imports.
            # This allows adding new network features (like OSPF or BGP) by simply dropping files into the folder.
            protocol_package = importlib.import_module(PROTOCOL_PACKAGE)
        except ImportError as error:
            raise ProtocolDiscoveryError(
                f"Unable to import protocol package '{PROTOCOL_PACKAGE}'."
            ) from error

        discovered_plugins: Dict[str, BaseProtocol] = {}
        module_prefix = f"{protocol_package.__name__}."

        # Scans the protocols package directory to discover all Python plugin files automatically.
        # Solves the problem of manually maintaining a list of active network protocol plugins.
        for module_info in sorted(
            pkgutil.iter_modules(protocol_package.__path__, module_prefix),
            key=lambda candidate: candidate.name,
        ):
            # Skip base_protocol.py because it is the abstract blueprint contract, not an executable feature plugin.
            if module_info.name.endswith(".base_protocol"):
                continue

            # Load the module, extract its concrete plugin classes, and instantiate them.
            plugin_module = self._import_plugin_module(module_info.name)
            for plugin_class in self._get_plugin_classes(plugin_module):
                plugin = self._instantiate_plugin(plugin_class, module_info.name)
                self._register_plugin(discovered_plugins, plugin, module_info.name)

        return discovered_plugins

    def generate(
        self,
        device_context: Mapping[str, Any],
        requested_protocols: Optional[Sequence[str]] = None,
        requested_interfaces: Optional[Sequence[str]] = None,
        excluded_interfaces: Optional[Sequence[str]] = None,
    ) -> str:
        """Generate configuration fragments for requested applicable plugins.

        Args:
            device_context: Unified context produced by ``ContextBuilder``.
            requested_protocols: Optional ordered protocol names supplied by the
                caller. When omitted, all discovered plugins are evaluated in
                deterministic protocol-name order.
            requested_interfaces: Optional sequence of target interface names.
                When provided, only configuration for matching interfaces is generated.
            excluded_interfaces: Optional sequence of interface names to exclude.
                When provided, excluded interfaces are omitted from generation.

        Returns:
            Newline-separated configuration fragments from applicable plugins.

        Raises:
            ConfigGenerationError: If requested plugins are unavailable or a
                plugin fails during generation.
            ProtocolValidationError: If an applicable plugin rejects its input.
        """
        # Filter device context interfaces if specific target interfaces were requested (and not 'all').
        if (
            requested_interfaces is not None
            and "all" not in [i.lower() for i in requested_interfaces]
        ):
            target_interfaces = set(requested_interfaces)
            current_interfaces = device_context.get("interfaces", {})
            if isinstance(current_interfaces, Mapping):
                filtered_interfaces = {
                    name: data
                    for name, data in current_interfaces.items()
                    if name in target_interfaces
                }
                device_context = dict(device_context)
                device_context["interfaces"] = filtered_interfaces

        # Filter out excluded interfaces if specified.
        if excluded_interfaces:
            excluded_set = {i.strip() for i in excluded_interfaces if i.strip()}
            current_interfaces = device_context.get("interfaces", {})
            if isinstance(current_interfaces, Mapping):
                filtered_interfaces = {
                    name: data
                    for name, data in current_interfaces.items()
                    if name not in excluded_set
                }
                device_context = dict(device_context)
                device_context["interfaces"] = filtered_interfaces

        # Discover all installed protocol plugins dynamically from disk.
        plugins = self.discover_plugins()
        # Filter plugins according to caller request or default to dependency priority order.
        selected_plugins = self._select_plugins(plugins, requested_protocols)
        configuration_fragments: List[str] = []

        for plugin in selected_plugins:
            # Check if this switch has settings for this protocol (e.g. does it have port security configured?).
            # If False, skip rendering to avoid generating empty or invalid CLI commands.
            if not plugin.is_applicable(device_context):
                logger.info("Skipping non-applicable protocol '%s'.", plugin.protocol_name)
                continue

            logger.info("Generating configuration for protocol '%s'.", plugin.protocol_name)
            # Verify data validity before generating commands so bad inputs are caught early.
            self._validate_plugin(plugin, device_context)
            # Render vendor CLI commands for this protocol and append to the output list.
            configuration_fragment = self._render_plugin(plugin, device_context)
            if configuration_fragment:
                configuration_fragments.append(configuration_fragment)

        # Join all generated CLI fragments with newlines into a single complete device configuration block.
        # This string is passed next to DeviceConnector to be executed on the physical network switch.
        return "\n".join(configuration_fragments)

    @staticmethod
    def _get_plugin_classes(plugin_module: Any) -> List[Type[BaseProtocol]]:
        """Return concrete plugin classes defined directly by a module."""
        # Use Python's inspect module to find classes that subclass BaseProtocol without being abstract.
        return [
            plugin_class
            for _, plugin_class in inspect.getmembers(plugin_module, inspect.isclass)
            if (
                issubclass(plugin_class, BaseProtocol)
                and plugin_class is not BaseProtocol
                and plugin_class.__module__ == plugin_module.__name__
                and not inspect.isabstract(plugin_class)
            )
        ]

    @staticmethod
    def _import_plugin_module(module_name: str) -> Any:
        """Import one plugin module with an actionable discovery error."""
        try:
            # Import a single plugin module by string name.
            return importlib.import_module(module_name)
        except Exception as error:
            raise ProtocolDiscoveryError(
                f"Unable to load protocol plugin module '{module_name}'."
            ) from error

    @staticmethod
    def _instantiate_plugin(
        plugin_class: Type[BaseProtocol],
        module_name: str,
    ) -> BaseProtocol:
        """Create one concrete plugin instance with a clear failure message."""
        try:
            # Call the class constructor to create an executable instance of the plugin.
            return plugin_class()
        except Exception as error:
            raise ProtocolDiscoveryError(
                f"Unable to initialize protocol plugin '{plugin_class.__name__}' "
                f"from '{module_name}'."
            ) from error

    @staticmethod
    def _register_plugin(
        discovered_plugins: Dict[str, BaseProtocol],
        plugin: BaseProtocol,
        module_name: str,
    ) -> None:
        """Validate plugin metadata and add the plugin to the discovery result."""
        protocol_name = plugin.protocol_name
        if not isinstance(protocol_name, str) or not protocol_name.strip():
            raise ProtocolDiscoveryError(
                f"Protocol plugin from '{module_name}' has an invalid protocol name."
            )
        # Prevent two plugins from registering under the same name, avoiding silent overwrites.
        if protocol_name in discovered_plugins:
            raise ProtocolDiscoveryError(
                f"Multiple protocol plugins declare the name '{protocol_name}'."
            )
        discovered_plugins[protocol_name] = plugin

    @staticmethod
    def _select_plugins(
        available_plugins: Mapping[str, BaseProtocol],
        requested_protocols: Optional[Sequence[str]],
    ) -> List[BaseProtocol]:
        """Select plugins while preserving explicit dependency priority order."""
        def get_priority_key(name: str) -> tuple:
            if name in PREFERRED_PROTOCOL_ORDER:
                return (PREFERRED_PROTOCOL_ORDER.index(name), name)
            return (len(PREFERRED_PROTOCOL_ORDER), name)

        # If no specific protocols were requested or 'all' is specified, return all available plugins sorted by priority order.
        if (
            requested_protocols is None
            or "all" in [p.lower() for p in requested_protocols]
        ):
            sorted_names = sorted(available_plugins.keys(), key=get_priority_key)
            return [available_plugins[name] for name in sorted_names]

        # Ensure requested protocol list has no duplicates to avoid generating identical CLI commands twice.
        if len(requested_protocols) != len(set(requested_protocols)):
            raise ConfigGenerationError("Requested protocol names must be unique.")

        # Check if any requested protocols are missing from available plugins and raise an error.
        unavailable_protocols = [
            protocol_name
            for protocol_name in requested_protocols
            if protocol_name not in available_plugins
        ]
        if unavailable_protocols:
            unavailable_names = ", ".join(unavailable_protocols)
            raise ConfigGenerationError(
                f"Requested protocol plugins are unavailable: {unavailable_names}."
            )

        # Sort requested protocols by dependency priority order
        sorted_requested = sorted(requested_protocols, key=get_priority_key)
        return [available_plugins[protocol_name] for protocol_name in sorted_requested]

    @staticmethod
    def _validate_plugin(
        plugin: BaseProtocol,
        device_context: Mapping[str, Any],
    ) -> None:
        """Run plugin validation while preserving actionable validation errors."""
        try:
            # Delegate context validation to the concrete plugin implementation.
            plugin.validate(device_context)
        except ProtocolValidationError:
            raise
        except Exception as error:
            raise ConfigGenerationError(
                f"Protocol '{plugin.protocol_name}' failed validation."
            ) from error

    @staticmethod
    def _render_plugin(
        plugin: BaseProtocol,
        device_context: Mapping[str, Any],
    ) -> str:
        """Render one plugin and verify that it returns a configuration string."""
        try:
            # Call plugin's render() method to generate vendor CLI text (e.g. Cisco switchport CLI).
            configuration_fragment = plugin.render(device_context)
        except Exception as error:
            raise ConfigGenerationError(
                f"Protocol '{plugin.protocol_name}' failed to render configuration."
            ) from error

        # Defensive check: ensure render() returned a string (not None or dict), preventing downstream SSH errors.
        if not isinstance(configuration_fragment, str):
            raise ConfigGenerationError(
                f"Protocol '{plugin.protocol_name}' returned a non-string configuration fragment."
            )
        return configuration_fragment

