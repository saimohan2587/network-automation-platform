"""SSH collector module for device_migration package."""

from typing import Dict, Any, List, Mapping

from post_deployment_validation.collectors.ssh_collector import SSHCollector
from device_migration.logger import get_logger

logger = get_logger("Collector")


class MigrationCollector:
    """Safe, read-only SSH state collector for migration discovery."""

    # Pre-defined list of read-only show commands to run on legacy switch
    REQUIRED_COMMANDS = [
        "show running-config",
        "show vlan brief",
        "show interfaces status",
        "show interfaces description",
        "show interfaces switchport",
        "show port-security",
        "show port-security interface",
        "show ntp status",
        "show running-config | include ntp",
        "show hosts",
        "show logging",
        "show snmp",
        "show aaa sessions",
        "show ip dhcp snooping",
        "show etherchannel summary",
        "show spanning-tree summary",
        "show vtp status",
    ]

    def __init__(self):
        # Instantiate SSH collector instance
        self.collector = SSHCollector()

    def collect_source_state(self, device_name: str, connection_details: Mapping[str, Any]) -> Dict[str, str]:
        """Collect read-only operational state from source device over SSH."""
        logger.info("Initiating read-only SSH discovery for source device '%s' (%s)...", device_name, connection_details.get("host"))
        # Execute commands via SSH without making any switch config modifications
        return self.collector.collect(device_name, connection_details, self.REQUIRED_COMMANDS)
