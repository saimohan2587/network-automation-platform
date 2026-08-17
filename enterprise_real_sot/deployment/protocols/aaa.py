"""
Purpose   : Protocol plugin generating AAA (Authentication, Authorization, Accounting) & TACACS+ server CLI commands.
Consumes  : NetBox Config Context (`config.aaa`).
Produces  : Cisco IOS CLI (`aaa new-model`, `tacacs server ...`, `aaa authentication login ...`).
"""

from typing import Any, List, Mapping, Sequence


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("AaaProtocol")


class AaaProtocol(BaseProtocol):
    """Render AAA new-model, authentication, authorization, and TACACS+ server CLI commands."""

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "aaa"

    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains AAA configuration."""
        settings = self._get_settings(device_context)
        return isinstance(settings, Mapping) and len(settings) > 0

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate AAA model, authentication, authorization, and TACACS+ servers."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "AAA settings must be a mapping.",
            )

        new_model = settings.get("new_model")
        if new_model is not None and not isinstance(new_model, bool):
            raise ProtocolValidationError(
                self.protocol_name,
                "AAA 'new_model' setting must be a boolean.",
            )

        tacacs_servers = settings.get("tacacs_servers")
        if tacacs_servers is not None:
            if not isinstance(tacacs_servers, Sequence):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "AAA tacacs_servers setting must be a list/sequence.",
                )
            for server in tacacs_servers:
                self._validate_tacacs_server(server)

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return AAA CLI configuration string."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            return ""

        commands: List[str] = []

        if settings.get("new_model") is True:
            commands.append("aaa new-model")

        # TACACS+ Servers
        tacacs_servers = settings.get("tacacs_servers") or []
        for index, server in enumerate(tacacs_servers, start=1):
            server_cmds = self._render_tacacs_server(index, server)
            if server_cmds:
                commands.extend(server_cmds)

        # AAA Authentication Method Lists
        auth = settings.get("authentication")
        if isinstance(auth, Mapping):
            login_methods = auth.get("login")
            if isinstance(login_methods, Mapping):
                for list_name, method_group in login_methods.items():
                    if isinstance(method_group, Sequence) and len(method_group) > 0:
                        methods_str = " ".join(str(m) for m in method_group)
                        commands.append(f"aaa authentication login {list_name} {methods_str}")

        # AAA Authorization Method Lists
        author = settings.get("authorization")
        if isinstance(author, Mapping):
            exec_methods = author.get("exec")
            if isinstance(exec_methods, Mapping):
                for list_name, method_group in exec_methods.items():
                    if isinstance(method_group, Sequence) and len(method_group) > 0:
                        methods_str = " ".join(str(m) for m in method_group)
                        commands.append(f"aaa authorization exec {list_name} {methods_str}")

        if commands:
            logger.info("Generated AAA configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_settings(device_context: Mapping[str, Any]) -> Any:
        """Extract AAA configuration dictionary from config context."""
        config = device_context.get("config", {})
        if not isinstance(config, Mapping):
            return None
        return config.get("aaa")

    def _validate_tacacs_server(self, server: Any) -> None:
        """Validate single TACACS+ server entry."""
        if not isinstance(server, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "TACACS+ server entry must be a mapping.",
            )
        address = server.get("address")
        if not isinstance(address, str) or not address.strip() or "\n" in address:
            raise ProtocolValidationError(
                self.protocol_name,
                "TACACS+ server address must be a valid single-line string.",
            )
        key = server.get("key")
        if key is not None and (not isinstance(key, str) or not key.strip() or "\n" in key):
            raise ProtocolValidationError(
                self.protocol_name,
                "TACACS+ server key must be a valid single-line string.",
            )

    @staticmethod
    def _render_tacacs_server(index: int, server: Any) -> List[str]:
        """Render Cisco IOS TACACS+ server CLI definition."""
        if not isinstance(server, Mapping):
            return []

        address = server.get("address")
        if not isinstance(address, str) or not address.strip():
            return []

        name = server.get("name", f"TACACS-SERVER-{index}")
        key = server.get("key")

        commands = [
            f"tacacs server {name}",
            f" address ipv4 {address.strip()}",
        ]
        if isinstance(key, str) and key.strip():
            commands.append(f" key {key.strip()}")

        return commands
