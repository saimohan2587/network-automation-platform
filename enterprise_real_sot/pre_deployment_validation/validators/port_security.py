"""Pre-deployment validation plugin for Port Security protocol."""

from typing import Any, List, Mapping, Optional, Sequence

from pre_deployment_validation.base_validator import BaseProtocolValidator
from pre_deployment_validation.report import (
    RULE_TYPE_POLICY,
    RULE_TYPE_TECHNICAL,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    ValidationCheckResult,
)


class PortSecurityValidator(BaseProtocolValidator):
    """Validator plugin verifying Port Security intent and rendered Cisco CLI configuration."""

    @property
    def validator_name(self) -> str:
        """Return unique validator string identifier."""
        return "port_security"

    @property
    def priority(self) -> int:
        """Return execution priority order."""
        return 100

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Check if target device platform supports Port Security."""
        platform = device_context.get("platform", "")
        if isinstance(platform, str):
            # Supports Cisco IOS / IOS-XE access switches
            return "cisco" in platform.lower() or platform == ""
        return True

    def is_configured(self, device_context: Mapping[str, Any]) -> bool:
        """Check if Port Security intent exists in NetBox interface custom fields."""
        interfaces = device_context.get("interfaces", [])
        if not isinstance(interfaces, list):
            return False

        for interface in interfaces:
            if not isinstance(interface, dict):
                continue
            custom_fields = interface.get("custom_fields", {})
            if isinstance(custom_fields, dict) and "port_security" in custom_fields:
                ps_data = custom_fields["port_security"]
                if isinstance(ps_data, dict) and ps_data.get("enabled") is True:
                    return True
        return False

    def validate(
        self,
        device: Mapping[str, Any],
        device_context: Mapping[str, Any],
        generated_configuration: str,
        requested_protocols: Optional[Sequence[str]] = None,
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Sequence[ValidationCheckResult]:
        """Validate Port Security NetBox intent against rendered Cisco CLI text."""
        results: List[ValidationCheckResult] = []
        device_name = str(device.get("name", "Unknown-Device"))
        interfaces = device_context.get("interfaces", [])

        if not isinstance(interfaces, list):
            return results

        target_interfaces = None
        if requested_interfaces is not None and "all" not in [
            i.lower() for i in requested_interfaces
        ]:
            target_interfaces = set(i.lower() for i in requested_interfaces)

        for interface in interfaces:
            if not isinstance(interface, dict):
                continue

            interface_name = interface.get("name")
            if not isinstance(interface_name, str):
                continue

            if target_interfaces and interface_name.lower() not in target_interfaces:
                continue

            custom_fields = interface.get("custom_fields", {})
            if not isinstance(custom_fields, dict):
                continue

            ps_config = custom_fields.get("port_security")
            if not isinstance(ps_config, dict) or not ps_config.get("enabled"):
                continue

            # -------------------------------------------------------------
            # Rule 1: Technical Check - Maximum MAC address range validation
            # -------------------------------------------------------------
            max_mac = ps_config.get("max_mac_addresses")
            if max_mac is not None:
                if not isinstance(max_mac, int) or max_mac < 1 or max_mac > 1024:
                    results.append(
                        ValidationCheckResult(
                            check_name=f"port_security_max_mac_range_{interface_name}",
                            passed=False,
                            severity=SEVERITY_ERROR,
                            rule_type=RULE_TYPE_TECHNICAL,
                            message=(
                                f"Device '{device_name}' interface {interface_name} max_mac_addresses "
                                f"value {max_mac} is outside valid Cisco bounds (1-1024)."
                            ),
                        )
                    )
                else:
                    results.append(
                        ValidationCheckResult(
                            check_name=f"port_security_max_mac_range_{interface_name}",
                            passed=True,
                            severity=SEVERITY_INFO,
                            rule_type=RULE_TYPE_TECHNICAL,
                            message=f"Interface {interface_name} max_mac_addresses ({max_mac}) in valid range.",
                        )
                    )

            # -------------------------------------------------------------
            # Rule 2: Technical Check - Violation mode syntax check
            # -------------------------------------------------------------
            violation_mode = ps_config.get("violation")
            valid_modes = {"protect", "restrict", "shutdown"}
            if violation_mode and (
                not isinstance(violation_mode, str)
                or violation_mode.lower() not in valid_modes
            ):
                results.append(
                    ValidationCheckResult(
                        check_name=f"port_security_violation_syntax_{interface_name}",
                        passed=False,
                        severity=SEVERITY_ERROR,
                        rule_type=RULE_TYPE_TECHNICAL,
                        message=(
                            f"Device '{device_name}' interface {interface_name} violation mode '{violation_mode}' "
                            f"is invalid. Must be one of: {sorted(valid_modes)}."
                        ),
                    )
                )
            elif violation_mode:
                results.append(
                    ValidationCheckResult(
                        check_name=f"port_security_violation_syntax_{interface_name}",
                        passed=True,
                        severity=SEVERITY_INFO,
                        rule_type=RULE_TYPE_TECHNICAL,
                        message=f"Interface {interface_name} violation mode '{violation_mode}' is valid.",
                    )
                )

            # -------------------------------------------------------------
            # Rule 3: Technical Check - Switchport mode access and Port Security enable presence
            # -------------------------------------------------------------
            if f"interface {interface_name}" in generated_configuration:
                if "switchport port-security" not in generated_configuration:
                    results.append(
                        ValidationCheckResult(
                            check_name=f"port_security_enable_cmd_{interface_name}",
                            passed=False,
                            severity=SEVERITY_ERROR,
                            rule_type=RULE_TYPE_TECHNICAL,
                            message=(
                                f"Device '{device_name}' interface {interface_name} missing required "
                                f"'switchport port-security' enable command in rendered CLI."
                            ),
                        )
                    )
                elif "switchport mode access" not in generated_configuration:
                    results.append(
                        ValidationCheckResult(
                            check_name=f"port_security_mode_access_{interface_name}",
                            passed=False,
                            severity=SEVERITY_ERROR,
                            rule_type=RULE_TYPE_TECHNICAL,
                            message=(
                                f"Device '{device_name}' interface {interface_name} missing required "
                                f"'switchport mode access' command before port security in rendered CLI."
                            ),
                        )
                    )
                else:
                    results.append(
                        ValidationCheckResult(
                            check_name=f"port_security_enable_cmd_{interface_name}",
                            passed=True,
                            severity=SEVERITY_INFO,
                            rule_type=RULE_TYPE_TECHNICAL,
                            message=f"Interface {interface_name} rendered switchport mode access and port-security enable commands.",
                        )
                    )

            # -------------------------------------------------------------
            # Rule 4: Enterprise Policy Check - Sticky MAC recommendation
            # -------------------------------------------------------------
            sticky_mac = ps_config.get("sticky_mac")
            if sticky_mac is False:
                results.append(
                    ValidationCheckResult(
                        check_name=f"port_security_policy_sticky_mac_{interface_name}",
                        passed=False,
                        severity=SEVERITY_WARNING,
                        rule_type=RULE_TYPE_POLICY,
                        message=(
                            f"Policy Alert: Device '{device_name}' interface {interface_name} has sticky MAC "
                            f"learning disabled. Enterprise policy recommends sticky MAC for access ports."
                        ),
                    )
                )
            else:
                results.append(
                    ValidationCheckResult(
                        check_name=f"port_security_policy_sticky_mac_{interface_name}",
                        passed=True,
                        severity=SEVERITY_INFO,
                        rule_type=RULE_TYPE_POLICY,
                        message=f"Interface {interface_name} complies with sticky MAC policy.",
                    )
                )

        return results
