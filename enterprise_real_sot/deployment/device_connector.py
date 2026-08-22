"""
Purpose   : Establishes SSH connection (via Netmiko) to physical switches and pushes generated CLI commands.
Called By : main.py (`DeploymentOrchestrator._deploy_candidate()`).
Calls Next: Physical Network Switch (Cisco IOS SSH), returning DeploymentResult to main.py.
"""

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, List, Mapping, Optional


from deployment.lifecycle import DeviceLifecycleState
from deployment.logger import get_logger


logger = get_logger("DeviceConnector")


class DeviceConnectorError(RuntimeError):
    """Base exception for device transport failures."""


class DeviceAuthenticationError(DeviceConnectorError):
    """Raised when a device rejects the supplied authentication details."""


class DeviceConnectionError(DeviceConnectorError):
    """Raised when a network device cannot be reached over SSH."""


class TransportUnavailableError(DeviceConnectorError):
    """Raised when the configured transport library is not installed."""


# Dataclass representing the immutable structured outcome of an SSH deployment execution.
# Retains status, total command count, elapsed time, and error messages for auditing and summary reports.
@dataclass(frozen=True)
class DeploymentResult:
    """Structured outcome of one device configuration deployment."""

    device_name: str
    ip_address: Optional[str]
    connection_status: str
    deployment_status: str
    commands_sent: int
    execution_time_seconds: float
    error_message: Optional[str] = None
    state: Optional[str] = None
    desired_items_count: int = 0
    compliant_items_count: int = 0
    change_required_count: int = 0
    backup_saved: bool = False
    rollback_status: str = "NOT_REQUIRED"
    verification_status: str = "SKIPPED"


class DeviceConnector:
    """Apply generated configuration to a device through an SSH transport."""

    def __init__(
        self,
        connection_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._connection_factory = connection_factory

    def deploy(
        self,
        device_name: str,
        connection_details: Mapping[str, Any],
        generated_configuration: str,
        save_config: bool = False,
    ) -> DeploymentResult:
        """Connect to a device, apply selective configuration changes, backup, verify, and handle rollback."""
        start_time = perf_counter()
        commands_sent = 0
        connection_status = "not_connected"
        deployment_status = "failed"
        error_message: Optional[str] = None
        connection: Optional[Any] = None
        ip_address = self._target_address(connection_details)

        desired_cmds = self._split_commands(generated_configuration)
        desired_count = len(desired_cmds)
        compliant_count = 0
        change_required_count = 0
        backup_saved = False
        rollback_status = "NOT_REQUIRED"
        verification_status = "SKIPPED"

        try:
            connection = self._connect(connection_details)
            connection_status = "connected"
            logger.info("Connected to device '%s' at '%s'.", device_name, ip_address)

            # Step 1: Pre-Change Backup
            running_config = ""
            if hasattr(connection, "send_command"):
                try:
                    running_config = connection.send_command("show running-config", read_timeout=60) or ""
                    backup_saved = True
                except Exception as audit_err:
                    logger.warning("Pre-change running-config retrieval warning on '%s': %s", device_name, audit_err)

            # Step 2: Change-Plan Classification (Selective Deployment)
            needed_commands = []
            compliant_commands = []
            for cmd in desired_cmds:
                cmd_clean = cmd.strip()
                if not cmd_clean or cmd_clean.startswith("!"):
                    continue
                if cmd_clean.startswith("interface ") or cmd_clean == "exit" or cmd_clean == "no shutdown" or cmd_clean == "shutdown":
                    needed_commands.append(cmd_clean)
                elif cmd_clean.startswith("ip address ") or cmd_clean.startswith("description "):
                    needed_commands.append(cmd_clean)
                else:
                    if running_config and cmd_clean in running_config:
                        compliant_commands.append(cmd_clean)
                    else:
                        needed_commands.append(cmd_clean)

            compliant_count = len(compliant_commands)
            change_required_count = len(needed_commands)

            # Save pre-change artifacts
            from datetime import datetime
            import json
            from pathlib import Path
            deployment_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            artifact_dir = Path("artifacts/deployments") / deployment_id / device_name
            artifact_dir.mkdir(parents=True, exist_ok=True)

            if running_config:
                with open(artifact_dir / "pre_change_running_config.txt", "w", encoding="utf-8") as f:
                    f.write(running_config)

            change_plan_payload = {
                "deployment_id": deployment_id,
                "device_name": device_name,
                "desired_items_count": desired_count,
                "compliant_items_count": compliant_count,
                "change_required_count": change_required_count,
                "compliant_commands": compliant_commands,
                "change_required_commands": needed_commands,
            }
            with open(artifact_dir / "change_plan.json", "w", encoding="utf-8") as f:
                json.dump(change_plan_payload, f, indent=2)

            with open(artifact_dir / "desired_config.cfg", "w", encoding="utf-8") as f:
                f.write(generated_configuration)

            # Idempotency Check: If device is already compliant
            if desired_count > 0 and change_required_count == 0 and running_config:
                logger.info("Device '%s' is ALREADY_COMPLIANT with NetBox SoT. 0 commands sent.", device_name)
                res = DeploymentResult(
                    device_name=device_name,
                    ip_address=ip_address,
                    connection_status=connection_status,
                    deployment_status="success",
                    commands_sent=0,
                    execution_time_seconds=perf_counter() - start_time,
                    error_message="Device configuration is ALREADY_COMPLIANT with NetBox SoT.",
                    state=DeviceLifecycleState.ALREADY_COMPLIANT.value,
                    desired_items_count=desired_count,
                    compliant_items_count=compliant_count,
                    change_required_count=0,
                    backup_saved=backup_saved,
                    rollback_status="NOT_REQUIRED",
                    verification_status="SUCCESS",
                )
                with open(artifact_dir / "deployment_result.json", "w", encoding="utf-8") as f:
                    json.dump(res.__dict__, f, indent=2)
                return res

            # Step 3: Selective Deployment Execution
            applied_commands = []
            if needed_commands:
                try:
                    config_output = connection.send_config_set(needed_commands, read_timeout=120)
                    commands_sent = len(needed_commands)
                    applied_commands = list(needed_commands)

                    # Check Cisco CLI rejection errors
                    if isinstance(config_output, str):
                        import re
                        error_match = re.search(
                            r"%\s*(?:Command rejected|Invalid input|Incomplete command|Ambiguous command|Error:|Bad IP address|Duplicate|Unknown command)",
                            config_output,
                            re.IGNORECASE,
                        )
                        if error_match:
                            error_lines = [
                                line.strip()
                                for line in config_output.splitlines()
                                if "%" in line or any(k in line.lower() for k in ["rejected", "invalid", "incomplete", "ambiguous", "error"])
                            ]
                            error_msg = "; ".join(error_lines) if error_lines else "Cisco CLI command rejected."
                            logger.error("CLI error on device '%s': %s. Attempting rollback...", device_name, error_msg)

                            # Attempt Rollback
                            rollback_ok = False
                            try:
                                logger.info("Executing safe rollback on '%s'...", device_name)
                                undo_cmds = []
                                for cmd in reversed(applied_commands):
                                    if cmd.startswith("ip ") or cmd.startswith("logging ") or cmd.startswith("snmp-server "):
                                        undo_cmds.append(f"no {cmd}")
                                if undo_cmds:
                                    connection.send_config_set(undo_cmds)
                                rollback_ok = True
                            except Exception as rb_err:
                                logger.error("Rollback failed on '%s': %s", device_name, rb_err)

                            final_rollback_state = (
                                DeviceLifecycleState.ROLLBACK_SUCCESSFUL.value
                                if rollback_ok
                                else DeviceLifecycleState.ROLLBACK_FAILED.value
                            )
                            rollback_status = "SUCCESSFUL" if rollback_ok else "FAILED"
                            return DeploymentResult(
                                device_name=device_name,
                                ip_address=ip_address,
                                connection_status=connection_status,
                                deployment_status="failed",
                                commands_sent=commands_sent,
                                execution_time_seconds=perf_counter() - start_time,
                                error_message=f"CLI error on switch: {error_msg}",
                                state=final_rollback_state,
                                desired_items_count=desired_count,
                                compliant_items_count=compliant_count,
                                change_required_count=change_required_count,
                                backup_saved=backup_saved,
                                rollback_status=rollback_status,
                                verification_status="FAILED",
                            )

                except Exception as send_err:
                    logger.error("Deployment execution error on '%s': %s", device_name, send_err)
                    return DeploymentResult(
                        device_name=device_name,
                        ip_address=ip_address,
                        connection_status=connection_status,
                        deployment_status="failed",
                        commands_sent=len(applied_commands),
                        execution_time_seconds=perf_counter() - start_time,
                        error_message=str(send_err),
                        state=DeviceLifecycleState.DEPLOYMENT_FAILED.value,
                        desired_items_count=desired_count,
                        compliant_items_count=compliant_count,
                        change_required_count=change_required_count,
                        backup_saved=backup_saved,
                        rollback_status="ATTEMPTED",
                        verification_status="FAILED",
                    )

            if save_config:
                logger.info("Saving running configuration to startup configuration on '%s'.", device_name)
                try:
                    connection.save_config(cmd="write memory")
                except Exception:
                    connection.save_config()

            final_state = DeviceLifecycleState.DEPLOYED.value
            deployment_status = "success"

            res = DeploymentResult(
                device_name=device_name,
                ip_address=ip_address,
                connection_status=connection_status,
                deployment_status=deployment_status,
                commands_sent=commands_sent,
                execution_time_seconds=perf_counter() - start_time,
                error_message=None,
                state=final_state,
                desired_items_count=desired_count,
                compliant_items_count=compliant_count,
                change_required_count=change_required_count,
                backup_saved=backup_saved,
                rollback_status="NOT_REQUIRED",
                verification_status="PENDING_COMPLIANCE",
            )
            with open(artifact_dir / "deployment_result.json", "w", encoding="utf-8") as f:
                json.dump(res.__dict__, f, indent=2)
            return res




        except DeviceAuthenticationError as error:
            connection_status = "authentication_failed"
            error_message = str(error)
            logger.error("Authentication failed for device '%s'.", device_name)
        except DeviceConnectionError as error:
            connection_status = "connection_failed"
            error_message = str(error)
            logger.error("SSH connection failed for device '%s': %s", device_name, error)
        except Exception as error:
            error_message = str(error)
            logger.error("Deployment failed for device '%s': %s", device_name, error)
        finally:
            # Always close SSH session in a finally block to avoid lingering open connections on switches.
            disconnect_error = self._disconnect(connection, device_name)
            if disconnect_error:
                connection_status = "disconnect_failed"
                if error_message is None:
                    error_message = disconnect_error

        # Return immutable deployment outcome report to caller (main.py).
        return DeploymentResult(
            device_name=device_name,
            ip_address=ip_address,
            connection_status=connection_status,
            deployment_status=deployment_status,
            commands_sent=commands_sent,
            execution_time_seconds=perf_counter() - start_time,
            error_message=error_message,
        )

    def _connect(self, connection_details: Mapping[str, Any]) -> Any:
        """Create a transport session using Netmiko or an injected factory."""
        connection_parameters = dict(connection_details)
        connection_parameters.setdefault("fast_cli", False)
        if self._connection_factory is not None:
            return self._connection_factory(**connection_parameters)

        try:
            # Lazy import Netmiko transport library only when establishing an active SSH connection.
            from netmiko import ConnectHandler
            from netmiko.cisco import CiscoIosSSH
            from netmiko.exceptions import (
                NetmikoAuthenticationException,
                NetmikoTimeoutException,
            )
        except ImportError as error:
            raise TransportUnavailableError(
                "Netmiko is required to establish the default device transport."
            ) from error

        class SafeCiscoIosSSH(CiscoIosSSH):
            def set_terminal_width(self, *args, **kwargs):
                return ""

        try:
            # Initialize Netmiko SSH transport session with host, device_type, username, and password parameters.
            device_type = connection_parameters.get("device_type", "cisco_ios")
            if device_type == "cisco_ios":
                return SafeCiscoIosSSH(**connection_parameters)
            return ConnectHandler(**connection_parameters)
        except NetmikoAuthenticationException as error:
            raise DeviceAuthenticationError(
                "Device authentication was rejected."
            ) from error
        except NetmikoTimeoutException as error:
            raise DeviceConnectionError(
                "SSH connection timed out or was refused."
            ) from error
        except OSError as error:
            raise DeviceConnectionError(
                "SSH connection could not be established."
            ) from error

    @staticmethod
    def _disconnect(connection: Optional[Any], device_name: str) -> Optional[str]:
        """Disconnect a session without masking the primary deployment result."""
        if connection is None:
            return None

        try:
            # Send exit/quit command to gracefully close SSH connection and release switch session locks.
            connection.disconnect()
            logger.info("Disconnected from device '%s'.", device_name)
            return None
        except Exception as error:
            logger.error("Failed to disconnect from device '%s': %s", device_name, error)
            return f"Device disconnect failed: {error}"

    @staticmethod
    def _split_commands(generated_configuration: str) -> List[str]:
        """Convert generated CLI text into non-empty commands for Netmiko."""
        if not isinstance(generated_configuration, str):
            raise DeviceConnectorError(
                "Generated configuration must be provided as a string."
            )
        # Split multiline config block by newlines and remove blank lines so empty commands aren't sent over SSH.
        return [
            command
            for command in generated_configuration.splitlines()
            if command.strip()
        ]

    @staticmethod
    def _target_address(connection_details: Mapping[str, Any]) -> Optional[str]:
        """Return the transport target for structured deployment reporting."""
        # Extract target IP/hostname from connection dict for logging and reporting.
        host = connection_details.get("host")
        return str(host) if host is not None else None

