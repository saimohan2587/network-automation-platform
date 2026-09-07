"""Unit and Integration Tests for ServiceNow ITSM Module.

Validates operational payload normalization, Prometheus/Loki evidence enrichment,
assignment group routing, deduplication lifecycle, and state transitions.
"""

import unittest
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from servicenow.models.incident_payload import ServiceNowIncidentPayload
from servicenow.client.servicenow_client import ServiceNowClient
from servicenow.config import settings


class TestServiceNowIntegration(unittest.TestCase):
    def setUp(self):
        self.test_storage_file = settings.STORAGE_DIR / "test_incidents.json"
        if self.test_storage_file.exists():
            self.test_storage_file.unlink()

        self.client = ServiceNowClient()
        self.client.storage_file = self.test_storage_file
        self.client.mock_mode = True
        self.client._ensure_storage()

    def tearDown(self):
        if self.test_storage_file.exists():
            self.test_storage_file.unlink()

    def test_payload_enrichment_and_assignment_routing(self):
        sample_alert_sw1 = {
            "status": "firing",
            "labels": {
                "alertname": "NetworkDeviceDown",
                "device_name": "SW1_gns3",
                "instance": "10.10.20.2",
                "site": "hyderabad",
                "device_role": "access_switch",
                "vendor_os": "cisco_ios",
                "severity": "CRITICAL",
            },
            "annotations": {
                "summary": "[CRITICAL] SW1_gns3 is UNREACHABLE",
                "problem": "Device Unreachable",
            },
            "startsAt": "2026-09-03T20:31:00Z",
            "fingerprint": "b2dee2c3d9d6ed87",
        }

        payload = ServiceNowIncidentPayload.from_alertmanager_alert(
            sample_alert_sw1,
            snmp_availability="0",
            last_relevant_syslog="SSH session closed unexpectedly"
        )

        self.assertEqual(payload.device_name, "SW1_gns3")
        self.assertEqual(payload.management_ip, "10.10.20.2")
        self.assertEqual(payload.assignment_group, "Network Switching")
        self.assertEqual(payload.snmp_availability, "0")
        self.assertIn("SSH session closed unexpectedly", payload.last_relevant_syslog)

        # Check Human Readable Description Format
        desc = payload.build_human_readable_description()
        self.assertIn("Device: SW1_gns3", desc)
        self.assertIn("Management IP: 10.10.20.2", desc)
        self.assertIn("SNMP Availability: 0", desc)
        self.assertIn("Assignment Group:", desc)
        self.assertIn("Network Switching", desc)

    def test_router_assignment_routing(self):
        sample_alert_r1 = {
            "status": "firing",
            "labels": {
                "alertname": "HighCPUUtilization",
                "device_name": "R1_gns3",
                "instance": "10.10.10.2",
                "site": "hyderabad",
                "device_role": "edge_router",
                "vendor_os": "cisco_ios",
                "severity": "HIGH",
            },
            "annotations": {
                "summary": "[HIGH] R1_gns3 CPU utilization at 92%",
                "problem": "High CPU utilization",
            },
            "startsAt": "2026-09-03T20:35:00Z",
            "fingerprint": "r1_cpu_high_hash",
        }

        payload = ServiceNowIncidentPayload.from_alertmanager_alert(
            sample_alert_r1,
            snmp_availability="1",
            last_relevant_syslog="%SYS-3-CPU_THRESHOLD: CPU 5-min average 92%"
        )

        self.assertEqual(payload.device_name, "R1_gns3")
        self.assertEqual(payload.assignment_group, "Network Routing")
        self.assertEqual(payload.snmp_availability, "1")

    def test_lifecycle_deduplication_and_resolution(self):
        sample_alert = {
            "status": "firing",
            "labels": {
                "alertname": "InterfaceDown",
                "device_name": "SW2_gns3",
                "instance": "10.10.30.2",
                "severity": "HIGH",
                "ifIndex": "1",
            },
            "annotations": {
                "summary": "GigabitEthernet0/0 on SW2_gns3 is DOWN",
                "problem": "Interface link down",
            },
            "startsAt": "2026-09-03T20:30:00Z",
            "fingerprint": "sw2_gig00_down",
        }

        # 1. Firing Alert -> CREATED
        payload1 = ServiceNowIncidentPayload.from_alertmanager_alert(sample_alert)
        action1, inc_num1 = self.client.process_alert_payload(payload1)
        self.assertEqual(action1, "CREATED")

        # 2. Repeated Firing Alert -> UPDATED_FIRING (No duplicate ticket created)
        payload2 = ServiceNowIncidentPayload.from_alertmanager_alert(sample_alert)
        action2, inc_num2 = self.client.process_alert_payload(payload2)
        self.assertEqual(action2, "UPDATED_FIRING")
        self.assertEqual(inc_num1, inc_num2)

        # 3. Resolved Alert -> RESOLVED
        sample_alert_res = dict(sample_alert)
        sample_alert_res["status"] = "resolved"
        payload3 = ServiceNowIncidentPayload.from_alertmanager_alert(sample_alert_res)
        action3, inc_num3 = self.client.process_alert_payload(payload3)
        self.assertEqual(action3, "RESOLVED")
        self.assertEqual(inc_num1, inc_num3)


if __name__ == "__main__":
    unittest.main()
