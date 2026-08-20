"""Parser engine wrapping existing compliance resource plugins for device_migration package."""

import re
from typing import Dict, Any, List, Optional

from post_deployment_validation.resources.vlan import VlanResource
from post_deployment_validation.resources.interface_base import InterfaceBaseResource
from post_deployment_validation.resources.port_security import PortSecurityResource
from post_deployment_validation.resources.dns import DnsResource
from post_deployment_validation.resources.ntp import NtpResource
from post_deployment_validation.resources.syslog import SyslogResource
from post_deployment_validation.resources.snmp import SnmpResource
from post_deployment_validation.resources.stp import StpResource
from post_deployment_validation.resources.vtp import VtpResource
from post_deployment_validation.resources.dhcp_snooping import DhcpSnoopingResource
from post_deployment_validation.resources.etherchannel import EtherChannelResource
from device_migration.logger import get_logger

logger = get_logger("ParserEngine")


class MigrationParserEngine:
    """Adapts resource validation plugins for extraction and normalization of operational state."""

    @staticmethod
    def parse_vlan_brief(raw_vlan_text: str, raw_config_text: str) -> List[Dict[str, Any]]:
        """Parse VLAN IDs, names, and descriptions from 'show vlan brief' and running-config."""
        vlans = []
        seen_vids = set()

        for line in raw_vlan_text.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("VLAN") or line_str.startswith("-"):
                continue

            parts = line_str.split()
            if len(parts) >= 2 and parts[0].isdigit():
                vid = int(parts[0])
                name = parts[1]

                if vid in (1, 1002, 1003, 1004, 1005):
                    continue

                if vid not in seen_vids:
                    seen_vids.add(vid)
                    vlans.append({
                        "vid": vid,
                        "name": name,
                        "description": f"{name} Segment"
                    })

        vlan_blocks = re.findall(r"^vlan\s+(\d+)\s*\n\s+name\s+(\S+)", raw_config_text, re.MULTILINE | re.IGNORECASE)
        for vid_str, name in vlan_blocks:
            vid = int(vid_str)
            if vid not in (1, 1002, 1003, 1004, 1005) and vid not in seen_vids:
                seen_vids.add(vid)
                vlans.append({
                    "vid": vid,
                    "name": name,
                    "description": f"{name} Segment"
                })

        return sorted(vlans, key=lambda x: x["vid"])

    @staticmethod
    def parse_running_config_interfaces(raw_config_text: str) -> Dict[str, Dict[str, Any]]:
        """Parse detailed per-interface configuration blocks from running-config."""
        intf_configs = {}
        current_intf = None

        for line in raw_config_text.splitlines():
            line_str = line.strip()
            if line_str.startswith("interface "):
                current_intf = line_str.split()[1]
                intf_configs[current_intf] = {
                    "raw_lines": [],
                    "description": "",
                    "switchport_mode": "access",
                    "access_vlan": 1,
                    "native_vlan": 1,
                    "trunk_allowed_vlans": [],
                    "port_security": {
                        "enabled": False,
                        "max_mac_addresses": 1,
                        "violation": "shutdown",
                        "aging_time": 0,
                        "aging_type": "absolute"
                    }
                }
            elif current_intf and line_str.startswith("!"):
                current_intf = None
            elif current_intf:
                cfg = intf_configs[current_intf]
                cfg["raw_lines"].append(line_str)

                if line_str.startswith("description "):
                    cfg["description"] = line_str.split("description ", 1)[1].strip()
                elif "switchport mode trunk" in line_str:
                    cfg["switchport_mode"] = "trunk"
                elif "switchport mode access" in line_str:
                    cfg["switchport_mode"] = "access"
                elif line_str.startswith("switchport access vlan "):
                    try:
                        cfg["access_vlan"] = int(line_str.split()[-1])
                    except ValueError:
                        pass
                elif line_str.startswith("switchport trunk native vlan "):
                    try:
                        cfg["native_vlan"] = int(line_str.split()[-1])
                    except ValueError:
                        pass
                elif line_str.startswith("switchport trunk allowed vlan "):
                    vlans_str = line_str.replace("switchport trunk allowed vlan ", "").replace("add ", "").strip()
                    cfg["trunk_allowed_vlans"].append(vlans_str)
                elif "switchport port-security" in line_str:
                    cfg["port_security"]["enabled"] = True
                    if "maximum " in line_str:
                        try:
                            cfg["port_security"]["max_mac_addresses"] = int(line_str.split()[-1])
                        except ValueError:
                            pass
                    elif "violation " in line_str:
                        cfg["port_security"]["violation"] = line_str.split()[-1].lower()
                    elif "aging time " in line_str:
                        try:
                            cfg["port_security"]["aging_time"] = int(line_str.split()[-1])
                        except ValueError:
                            pass
                    elif "aging type " in line_str:
                        cfg["port_security"]["aging_type"] = line_str.split()[-1].lower()

        return intf_configs

    @classmethod
    def parse_all_protocols(cls, raw_outputs: Dict[str, str]) -> Dict[str, Any]:
        """Parse all system protocols using existing validation resource plugins."""
        dummy_context = {"platform": {"slug": "cisco_ios"}, "config": {}}

        dns_plugin = DnsResource()
        dns_actual = dns_plugin.parse_actual_state(raw_outputs, dummy_context, {})

        ntp_plugin = NtpResource()
        ntp_actual = ntp_plugin.parse_actual_state(raw_outputs, dummy_context, {})

        syslog_plugin = SyslogResource()
        syslog_actual = syslog_plugin.parse_actual_state(raw_outputs, dummy_context, {})

        snmp_plugin = SnmpResource()
        snmp_actual = snmp_plugin.parse_actual_state(raw_outputs, dummy_context, {})

        stp_plugin = StpResource()
        stp_actual = stp_plugin.parse_actual_state(raw_outputs, dummy_context, {})

        vtp_plugin = VtpResource()
        vtp_actual = vtp_plugin.parse_actual_state(raw_outputs, dummy_context, {})

        dhcp_plugin = DhcpSnoopingResource()
        dhcp_actual = dhcp_plugin.parse_actual_state(raw_outputs, dummy_context, {})

        eth_plugin = EtherChannelResource()
        eth_actual = eth_plugin.parse_actual_state(raw_outputs, dummy_context, {})

        raw_config = raw_outputs.get("show running-config", "")
        raw_vlan = raw_outputs.get("show vlan brief", "")
        vlans_list = cls.parse_vlan_brief(raw_vlan, raw_config)

        return {
            "dns": dns_actual,
            "ntp": ntp_actual,
            "syslog": syslog_actual,
            "snmp": snmp_actual,
            "stp": stp_actual,
            "vtp": vtp_actual,
            "dhcp_snooping": dhcp_actual,
            "etherchannel": eth_actual,
            "vlans": vlans_list
        }

    @staticmethod
    def parse_discovered_interfaces(raw_outputs: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        Dynamically parse interface inventory from live CLI outputs:
        'show ip interface brief' and 'show interfaces'.
        """
        interfaces_map: Dict[str, Dict[str, Any]] = {}
        ip_brief_text = raw_outputs.get("show ip interface brief", "")

        for line in ip_brief_text.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("Interface") or line_str.startswith("-"):
                continue

            match = re.match(
                r"^(\S+)\s+(\S+)\s+(?:YES|NO)\s+\S+\s+(up|down|administratively down)\s+(up|down)",
                line_str,
                re.IGNORECASE
            )
            if match:
                name, ip_addr, status, protocol = match.groups()
                interfaces_map[name] = {
                    "name": name,
                    "ip_address": ip_addr if ip_addr.lower() != "unassigned" else None,
                    "admin_status": status.lower(),
                    "protocol_status": protocol.lower(),
                    "description": "",
                    "hardware_type": "other",
                    "enabled": status.lower() != "administratively down"
                }

        raw_interfaces_text = raw_outputs.get("show interfaces", "")
        current_intf = None

        for line in raw_interfaces_text.splitlines():
            intf_header = re.match(r"^(\S+) is (up|down|administratively down),\s+line protocol is (up|down)", line, re.IGNORECASE)
            if intf_header:
                current_intf = intf_header.group(1)
                if current_intf not in interfaces_map:
                    interfaces_map[current_intf] = {
                        "name": current_intf,
                        "ip_address": None,
                        "admin_status": intf_header.group(2).lower(),
                        "protocol_status": intf_header.group(3).lower(),
                        "description": "",
                        "hardware_type": "other",
                        "enabled": intf_header.group(2).lower() != "administratively down"
                    }
                continue

            if current_intf and "Description:" in line:
                desc = line.split("Description:", 1)[1].strip()
                interfaces_map[current_intf]["description"] = desc

            if current_intf and "Hardware is" in line:
                hw = line.split("Hardware is", 1)[1].split(",")[0].strip()
                interfaces_map[current_intf]["hardware_type"] = hw

            if current_intf and "Internet address is" in line:
                ip_cidr = line.split("Internet address is", 1)[1].strip().split()[0]
                interfaces_map[current_intf]["ip_address"] = ip_cidr

        return list(interfaces_map.values())
