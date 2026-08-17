"""
Purpose   : Resolves SSH credentials, target IP addresses, and Netmiko platform drivers for devices.
Called By : main.py (`DeploymentOrchestrator._assess_device()`).
Calls Next: Returns connection parameters dictionary to main.py.
"""

from typing import Any, Dict, Mapping, Optional

from deployment import config
from deployment.logger import get_logger


# Initialize logger for credential resolver module
logger = get_logger("CredentialResolver")


class CredentialResolutionError(RuntimeError):
    """Raised when connection parameters or credentials cannot be resolved for a device."""


class CredentialResolver:
    """Dynamically resolves network device connection parameters and SSH credentials.

    Converts non-secret NetBox device metadata (primary_ip4, platform, role)
    and environment credential profiles into Netmiko-compatible connection dicts.
    Secrets are never retrieved from NetBox or hardcoded.
    """

    def resolve_connection_details(
        self, device: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """Resolve full connection parameters dict for a single NetBox device."""
        # Extract device name for error reporting and logging
        device_name = device.get("name", "unknown")

        # 1. Resolve target management IP address from NetBox primary_ip4 object
        host_ip = self._extract_management_ip(device)
        if not host_ip:
            raise CredentialResolutionError(
                f"Device '{device_name}' does not have a primary IPv4 address configured in NetBox."
            )

        # 2. Resolve Netmiko device type platform driver
        device_type = self._extract_device_type(device)

        # 3. Determine credential profile name (derived from device role or site)
        profile_name = self._determine_profile_name(device)

        # 4. Fetch profile credentials from environment variable lookup
        creds = config.get_profile_credentials(profile_name)

        # Log successful connection parameter resolution details
        logger.info(
            "Resolved connection details for device '%s': host=%s, profile=%s, driver=%s",
            device_name,
            host_ip,
            profile_name,
            device_type,
        )

        # Build and return Netmiko-compatible dictionary
        return {
            "host": host_ip,
            "username": creds["username"],
            "password": creds["password"],
            "secret": creds["secret"],
            "device_type": device_type,
            "port": config.SSH_PORT,
            "timeout": config.SSH_TIMEOUT,
        }

    @staticmethod
    def _extract_management_ip(device: Mapping[str, Any]) -> Optional[str]:
        """Extract IP address string from primary_ip4 dictionary, stripping CIDR mask."""
        # Check both primary_ip4 and fallback primary_ip dictionary keys
        primary_ip = device.get("primary_ip4") or device.get("primary_ip")
        if isinstance(primary_ip, Mapping):
            raw_address = primary_ip.get("address", "")
            if isinstance(raw_address, str) and raw_address:
                # Strip network prefix CIDR mask (e.g., '192.168.1.20/24' -> '192.168.1.20')
                return raw_address.split("/")[0]
        return None

    @staticmethod
    def _extract_device_type(device: Mapping[str, Any]) -> str:
        """Map NetBox platform slug to Netmiko driver string."""
        # Extract platform dictionary from NetBox device metadata
        platform = device.get("platform")
        if isinstance(platform, Mapping):
            slug = platform.get("slug", "")
            if slug:
                # Convert NetBox hyphens to Netmiko underscores (e.g., 'cisco-ios' -> 'cisco_ios')
                return slug.replace("-", "_")
        # Default fallback to cisco_ios driver
        return "cisco_ios"

    @staticmethod
    def _determine_profile_name(device: Mapping[str, Any]) -> str:
        """Determine credential profile key based on device name, role, or default."""
        import os
        device_name = device.get("name", "")
        if isinstance(device_name, str) and device_name:
            dev_key = device_name.lower().replace("-", "_")
            if os.getenv(f"SSH_{dev_key.upper()}_USERNAME"):
                return device_name

        # Extract device role dictionary from NetBox metadata
        role = device.get("role") or device.get("device_role")
        if isinstance(role, Mapping):
            role_slug = role.get("slug", "")
            if role_slug:
                # Match access switch roles to access credential profile
                if "access" in role_slug:
                    return "access"
                # Match core switch roles to core credential profile
                if "core" in role_slug:
                    return "core"
                # Match distribution switch roles to distribution credential profile
                if "dist" in role_slug:
                    return "distribution"
                return role_slug
        # Default fallback profile key
        return "default"
