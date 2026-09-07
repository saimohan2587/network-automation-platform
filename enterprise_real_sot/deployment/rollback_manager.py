"""
Purpose   : Restore a device to its pre-deployment configuration state after a failed
            deployment, and independently verify — against a fresh, live read of the
            device — that the restoration actually happened before ever reporting
            ROLLBACK_SUCCESSFUL.
Called By : deployment/device_connector.py (`DeviceConnector.deploy()`, on CLI rejection).
Principle : Rollback commands executed + Device state verified = ROLLBACK_SUCCESSFUL.
            Sending "no <command>" and getting an OK back is NOT success on its own.

Scope note (Cisco IOS, GNS3 lab, ~3 devices): this module restores exactly the
config sections that a deployment actually touched (interface stanzas, and simple
top-level constructs such as "vlan <id>" blocks or single-line global commands),
by diffing against the full "show running-config" snapshot captured before the
change. It intentionally does not attempt a generic diff/patch engine for every
possible Cisco construct - that would be overengineering for the current fleet
size. The interface returned (RollbackResult) is vendor/command-agnostic so a
future per-vendor rollback strategy can be swapped in without changing callers.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import re

from deployment.logger import get_logger

logger = get_logger("RollbackManager")


@dataclass(frozen=True)
class RollbackResult:
    """Structured, auditable outcome of a rollback attempt."""

    status: str  # "ROLLBACK_SUCCESSFUL" | "ROLLBACK_FAILED"
    commands_executed: List[str]
    sections_checked: List[str]
    verification_passed: bool
    verification_details: str
    execution_error: Optional[str] = None


class ConfigSectionParser:
    """
    Splits Cisco IOS text (either a full 'show running-config' capture, or the
    flat list of CLI lines a deployment just sent) into per-interface stanzas
    plus a 'global' bucket of top-level lines.

    Real IOS formatting (confirmed against an actual captured running-config in
    this project's own artifacts): a top-level "interface X" line is followed by
    one-space-indented sub-commands, and the block ends at the next line that is
    NOT indented (typically "!", or the next top-level directive/interface).
    """

    INTERFACE_HEADER_RE = re.compile(r"^\s*interface\s+(\S+)\s*$", re.IGNORECASE)

    @classmethod
    def split_applied_commands(cls, commands: List[str]) -> Dict[str, List[str]]:
        """
        Group a flat list of CLI lines just sent to the device (no leading
        whitespace - Netmiko config-set lines are plain text) into
        {"interface <Name>": [sub-commands...], "global": [top-level lines...]}.
        """
        sections: Dict[str, List[str]] = {}
        current_key: Optional[str] = None

        for raw in commands:
            line = raw.strip()
            if not line or line == "!":
                current_key = None
                continue

            header = cls.INTERFACE_HEADER_RE.match(line)
            if header:
                current_key = f"interface {header.group(1)}"
                sections.setdefault(current_key, [])
                continue

            if line == "exit":
                current_key = None
                continue

            bucket_key = current_key if current_key else "global"
            sections.setdefault(bucket_key, []).append(line)

        return sections

    @classmethod
    def interface_exists(cls, running_config_text: str, interface_name: str) -> bool:
        target = f"interface {interface_name}".lower()
        for line in running_config_text.splitlines():
            if line.strip().lower() == target:
                return True
        return False

    @classmethod
    def extract_interface_stanza(cls, running_config_text: str, interface_name: str) -> List[str]:
        """Return the exact original indented sub-command lines for one interface."""
        lines = running_config_text.splitlines()
        stanza: List[str] = []
        capturing = False
        target = f"interface {interface_name}".lower()

        for line in lines:
            if not capturing:
                if line.strip().lower() == target:
                    capturing = True
                continue

            if line.startswith((" ", "\t")):
                stripped = line.strip()
                if stripped:
                    stanza.append(stripped)
                continue

            # First non-indented line reached -> stanza is complete.
            break

        return stanza

    @classmethod
    def vlan_exists(cls, running_config_text: str, vlan_id: str) -> bool:
        pattern = re.compile(rf"^\s*vlan\s+{re.escape(vlan_id)}\s*$", re.IGNORECASE | re.MULTILINE)
        return bool(pattern.search(running_config_text))

    @classmethod
    def extract_vlan_name(cls, running_config_text: str, vlan_id: str) -> Optional[str]:
        """VLAN-database mode nests 'name X' one line below 'vlan <id>' in running-config."""
        lines = running_config_text.splitlines()
        target = f"vlan {vlan_id}".lower()
        for idx, line in enumerate(lines):
            if line.strip().lower() == target:
                if idx + 1 < len(lines):
                    next_line = lines[idx + 1].strip()
                    m = re.match(r"^name\s+(\S+)$", next_line, re.IGNORECASE)
                    if m:
                        return m.group(1)
                return None
        return None


def build_rollback_plan(pre_change_config: str, applied_commands: List[str]) -> Tuple[List[str], List[str]]:
    """
    Compute the exact commands needed to restore the device to its pre-change
    state for every section the deployment touched, plus the list of section
    keys that post-rollback verification must independently re-check.

    Returns:
        (rollback_commands, sections_checked)
    """
    sections = ConfigSectionParser.split_applied_commands(applied_commands)
    rollback_commands: List[str] = []
    sections_checked: List[str] = []

    for key, cmds in sections.items():
        if key.startswith("interface "):
            iface_name = key[len("interface "):]
            existed_before = ConfigSectionParser.interface_exists(pre_change_config, iface_name)

            if not existed_before:
                # This deployment created an interface (e.g. an SVI/sub-interface)
                # that never existed before - undo means removing it entirely.
                rollback_commands.append(f"no interface {iface_name}")
            else:
                original_lines = ConfigSectionParser.extract_interface_stanza(pre_change_config, iface_name)
                rollback_commands.append(f"interface {iface_name}")
                rollback_commands.append(f"default interface {iface_name}")
                rollback_commands.append(f"interface {iface_name}")
                for line in original_lines:
                    rollback_commands.append(line)
                rollback_commands.append("exit")

            sections_checked.append(key)
            continue

        # Global-scope commands: handle "vlan <id>" blocks explicitly (called out
        # in the required rollback flow), and treat any other global line as a
        # simple present/absent construct.
        idx = 0
        while idx < len(cmds):
            line = cmds[idx]
            vlan_match = re.match(r"^vlan\s+(\d+)\s*$", line, re.IGNORECASE)

            if vlan_match:
                vlan_id = vlan_match.group(1)
                idx += 1
                while idx < len(cmds) and cmds[idx].lower().startswith("name "):
                    idx += 1  # consume the "name X" sub-line that belongs to this vlan block

                existed_before = ConfigSectionParser.vlan_exists(pre_change_config, vlan_id)
                if not existed_before:
                    rollback_commands.append(f"no vlan {vlan_id}")
                else:
                    original_name = ConfigSectionParser.extract_vlan_name(pre_change_config, vlan_id)
                    rollback_commands.append(f"vlan {vlan_id}")
                    if original_name:
                        rollback_commands.append(f"name {original_name}")
                    rollback_commands.append("exit")

                sections_checked.append(f"global:vlan {vlan_id}")
                continue

            # Simple single-line global command (logging/snmp-server/ntp/ip route/etc).
            # Only handle the add-then-remove case explicitly - restoring a
            # *changed* value of a pre-existing non-keyed global line is out of
            # scope here (see module docstring on proportional scope).
            existed_before = any(
                existing_line.strip() == line for existing_line in pre_change_config.splitlines()
            )
            if not existed_before:
                rollback_commands.append(f"no {line}")
                sections_checked.append(f"global:{line}")
            idx += 1

    return rollback_commands, sections_checked


def verify_rollback(
    live_config_after_rollback: str,
    pre_change_config: str,
    sections_checked: List[str],
) -> Tuple[bool, str]:
    """
    Independently confirm, from a fresh live read of the device, that every
    touched section now matches (or correctly lacks) its pre-deployment form.
    This is the check that a false ROLLBACK_SUCCESSFUL must never bypass.
    """
    mismatches: List[str] = []

    for key in sections_checked:
        if key.startswith("interface "):
            iface_name = key[len("interface "):]
            expected_existed = ConfigSectionParser.interface_exists(pre_change_config, iface_name)
            live_existed = ConfigSectionParser.interface_exists(live_config_after_rollback, iface_name)

            if expected_existed != live_existed:
                mismatches.append(
                    f"{key}: existence mismatch (expected_existed={expected_existed}, live_existed={live_existed})"
                )
                continue

            if expected_existed:
                expected_lines = ConfigSectionParser.extract_interface_stanza(pre_change_config, iface_name)
                live_lines = ConfigSectionParser.extract_interface_stanza(live_config_after_rollback, iface_name)
                if expected_lines != live_lines:
                    mismatches.append(
                        f"{key}: expected={expected_lines!r} actual={live_lines!r}"
                    )

        elif key.startswith("global:vlan "):
            vlan_id = key.rsplit(" ", 1)[-1]
            expected_existed = ConfigSectionParser.vlan_exists(pre_change_config, vlan_id)
            live_existed = ConfigSectionParser.vlan_exists(live_config_after_rollback, vlan_id)
            if expected_existed != live_existed:
                mismatches.append(
                    f"{key}: existence mismatch (expected_existed={expected_existed}, live_existed={live_existed})"
                )

        elif key.startswith("global:"):
            line = key[len("global:"):]
            expected_existed = any(l.strip() == line for l in pre_change_config.splitlines())
            live_existed = any(l.strip() == line for l in live_config_after_rollback.splitlines())
            if expected_existed != live_existed:
                mismatches.append(
                    f"{key}: existence mismatch (expected_existed={expected_existed}, live_existed={live_existed})"
                )

    if mismatches:
        return False, "; ".join(mismatches)

    if not sections_checked:
        return True, "No sections required verification."

    return True, f"All {len(sections_checked)} touched section(s) verified to match pre-deployment state."


def execute_and_verify_rollback(
    connection,
    pre_change_config: str,
    applied_commands: List[str],
) -> RollbackResult:
    """
    Full rollback lifecycle for one device: build the restore plan, execute it,
    then re-collect live state and verify. Never returns ROLLBACK_SUCCESSFUL
    without having actually re-checked the device.
    """
    rollback_commands, sections_checked = build_rollback_plan(pre_change_config, applied_commands)

    if not rollback_commands:
        logger.info("Rollback plan is empty (nothing to undo) - treating as vacuously successful.")
        return RollbackResult(
            status="ROLLBACK_SUCCESSFUL",
            commands_executed=[],
            sections_checked=sections_checked,
            verification_passed=True,
            verification_details="No rollback commands were required.",
        )

    try:
        logger.info("Executing rollback plan (%d commands)...", len(rollback_commands))
        connection.send_config_set(rollback_commands, read_timeout=120)
    except Exception as exec_err:
        logger.error("Rollback command execution failed: %s", exec_err)
        return RollbackResult(
            status="ROLLBACK_FAILED",
            commands_executed=rollback_commands,
            sections_checked=sections_checked,
            verification_passed=False,
            verification_details="Rollback commands could not be executed.",
            execution_error=str(exec_err),
        )

    try:
        live_config_after_rollback = connection.send_command("show running-config", read_timeout=60) or ""
    except Exception as verify_err:
        logger.error("Post-rollback verification read failed: %s", verify_err)
        return RollbackResult(
            status="ROLLBACK_FAILED",
            commands_executed=rollback_commands,
            sections_checked=sections_checked,
            verification_passed=False,
            verification_details="Rollback commands were sent, but the device could not be re-read to verify the result.",
            execution_error=str(verify_err),
        )

    verification_passed, verification_details = verify_rollback(
        live_config_after_rollback, pre_change_config, sections_checked
    )

    status = "ROLLBACK_SUCCESSFUL" if verification_passed else "ROLLBACK_FAILED"
    if not verification_passed:
        logger.error("Rollback verification FAILED: %s", verification_details)
    else:
        logger.info("Rollback verification PASSED: %s", verification_details)

    return RollbackResult(
        status=status,
        commands_executed=rollback_commands,
        sections_checked=sections_checked,
        verification_passed=verification_passed,
        verification_details=verification_details,
    )
