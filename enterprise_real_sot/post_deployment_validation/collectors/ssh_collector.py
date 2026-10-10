"""Read-only SSH data collector using Netmiko."""

from typing import Any, Dict, List, Mapping

from netmiko import ConnectHandler
from netmiko.exceptions import (
    ConnectionException,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

from post_deployment_validation.collectors.base_collector import (
    BaseCollector,
    CollectionError,
    DeviceUnreachableError,
)
from post_deployment_validation.logger import get_logger

# Exceptions that mean the device itself could not be reached/authenticated to
# -- SSH timeout, TCP connection refused, network unreachable, DNS failure, or
# the device rejecting our SSH credentials -- as opposed to a bug in our own
# parsing/collection code. OSError covers the raw socket-level failures (e.g.
# paramiko's NoValidConnectionsError, ConnectionRefusedError, socket.gaierror)
# that occur before Netmiko even gets far enough to raise its own exception.
_UNREACHABLE_EXCEPTIONS = (
    NetmikoTimeoutException,
    NetmikoAuthenticationException,
    ConnectionException,
    OSError,
)

logger = get_logger("SSHCollector")


class SSHCollector(BaseCollector):
    """Read-only SSH collector executing show commands over Netmiko transport.

    SAFETY GUARANTEE: Never issues configuration commands, send_config_set(),
    or configuration saves.
    """

    def collect(
        self,
        device_name: str,
        connection_details: Mapping[str, Any],
        commands_or_requests: List[str],
    ) -> Dict[str, str]:
        """Establish SSH connection and execute read-only show commands."""
        if not commands_or_requests:
            return {}

        host = connection_details.get("host")
        device_type = connection_details.get("device_type", "cisco_ios")

        logger.info(
            "Connecting to device '%s' (%s) via SSH for read-only collection...",
            device_name,
            host,
        )

        netmiko_params = {
            "device_type": device_type,
            "host": host,
            "username": connection_details.get("username"),
            "password": connection_details.get("password"),
            "secret": connection_details.get("secret", ""),
            "port": connection_details.get("port", 22),
            "timeout": connection_details.get("timeout", 30),
            "auth_timeout": 30,
            "banner_timeout": 30,
            "conn_timeout": 30,
            "fast_cli": False,
        }

        raw_results: Dict[str, str] = {}
        netmiko_handler = None
        try:
            if device_type == "cisco_ios":
                from netmiko.cisco import CiscoIosSSH

                class SafeCiscoIosSSH(CiscoIosSSH):
                    def set_terminal_width(self, *args, **kwargs):
                        return ""

                netmiko_handler = SafeCiscoIosSSH(**netmiko_params)
            else:
                netmiko_handler = ConnectHandler(**netmiko_params)

            # Enter enable mode if secret is provided and device is in unprivileged mode
            if netmiko_params["secret"]:
                netmiko_handler.enable()

            for command in commands_or_requests:
                logger.info(
                    "Executing read-only command on '%s': '%s'", device_name, command
                )
                # STRICTLY READ-ONLY: send_command executes show command without config mode
                output = netmiko_handler.send_command(command, read_timeout=30)
                raw_results[command] = output if isinstance(output, str) else str(output)

            return raw_results

        except _UNREACHABLE_EXCEPTIONS as unreachable_error:
            message = f"Device '{device_name}' is unreachable for read-only collection: {unreachable_error}"
            logger.error(message)
            raise DeviceUnreachableError(message) from unreachable_error

        except Exception as error:
            message = f"SSH data collection failed for '{device_name}': {error}"
            logger.error(message)
            raise CollectionError(message) from error

        finally:
            if netmiko_handler is not None:
                try:
                    netmiko_handler.disconnect()
                    logger.info("Disconnected SSH session from '%s'.", device_name)
                except Exception as close_error:
                    logger.warning("Error closing SSH session to '%s': %s", device_name, close_error)
