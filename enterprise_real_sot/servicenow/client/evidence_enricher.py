"""Telemetry Evidence Enricher for ServiceNow Integration.

Queries Prometheus for live SNMP metric baselines and Loki for relevant syslog events
to enrich ServiceNow Incidents with operational evidence without duplicating raw logs.
"""

import json
import logging
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("EvidenceEnricher")

PROMETHEUS_URL = "http://prometheus:9090"
LOKI_URL = "http://loki:3100"


class TelemetryEvidenceEnricher:
    def __init__(self, prometheus_url: str = PROMETHEUS_URL, loki_url: str = LOKI_URL):
        self.prometheus_url = prometheus_url.rstrip("/")
        self.loki_url = loki_url.rstrip("/")

    def get_snmp_availability(self, device_name: str) -> str:
        """Query Prometheus for device SNMP availability (1=UP, 0=DOWN)."""
        query = f'up{{device_name="{device_name}"}}'
        url = f"{self.prometheus_url}/api/v1/query?query=" + urllib.parse.quote(query)
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                result = data.get("data", {}).get("result", [])
                if result:
                    val = result[0].get("value", [None, "0"])[1]
                    return val
        except Exception as e:
            logger.warning(f"Could not query Prometheus SNMP availability for {device_name}: {e}")
        return "0"

    def get_last_relevant_syslog(self, device_name: str) -> str:
        """Query Loki for the single most recent relevant syslog event for target device."""
        query = f'{{job="syslog"}} |~ "(?i){device_name}|down|closed|fail|error|config"'
        url = f"{self.loki_url}/loki/api/v1/query_range?query=" + urllib.parse.quote(query) + "&limit=1"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                streams = data.get("data", {}).get("result", [])
                if streams and "values" in streams[0]:
                    values = streams[0]["values"]
                    if values and len(values[0]) > 1:
                        raw_log = values[0][1].strip()
                        return raw_log
        except Exception as e:
            logger.warning(f"Could not query Loki syslog for {device_name}: {e}")
        return "No recent relevant syslog events found"

    def enrich_evidence(self, device_name: str) -> Dict[str, str]:
        """Collect enriched evidence dict combining Prometheus & Loki data."""
        availability = self.get_snmp_availability(device_name)
        syslog_line = self.get_last_relevant_syslog(device_name)
        return {
            "snmp_availability": availability,
            "last_relevant_syslog": syslog_line,
        }
