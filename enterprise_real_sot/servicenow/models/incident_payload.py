"""ServiceNow Incident Data Contract & Operational Payload Normalization Model.

Enforces strict data structure matching enterprise ServiceNow Incident schema.
Enriches alert metadata with Prometheus SNMP availability & Loki syslog evidence.
Centralizes assignment group routing (Network Routing vs Network Switching).
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
import hashlib
import time

from servicenow.config import settings


@dataclass
class ServiceNowIncidentPayload:
    # Device Information
    device_name: str
    management_ip: str
    site: str
    device_role: str
    vendor_os: str

    # Incident Information
    alert_name: str
    severity: str
    alert_status: str  # 'firing' or 'resolved'
    problem_type: str
    recommended_action: str
    first_detected: str
    last_updated: str

    # Monitoring Evidence (Prometheus + Loki)
    snmp_availability: str
    last_relevant_syslog: str
    metric_value: str
    affected_interface: str

    # Correlation & Assignment Group Mapping
    alert_group: str
    fingerprint: str
    assignment_group: str
    priority: str = "3 - Moderate"
    source: str = "Prometheus / Alertmanager"

    # Incident Lifecycle & Resolution
    state: str = "New"
    resolution_reason: Optional[str] = None
    resolution_notes: Optional[str] = None

    def build_human_readable_description(self) -> str:
        """Construct concise, operationally useful human-readable incident description."""
        lines = [
            "--------------------------------------------------",
            "Network Device Alert",
            "",
            f"Device: {self.device_name}",
            f"Management IP: {self.management_ip}",
            f"Role: {self.device_role}",
            f"Vendor OS: {self.vendor_os}",
            f"Alert: {self.alert_name}",
            f"Severity: {self.severity}",
            f"Problem Type: {self.problem_type}",
            "",
            f"Detected: {self.first_detected}",
            f"SNMP Availability: {self.snmp_availability}",
            "",
            "Recommended Action:",
            f"{self.recommended_action}",
            "",
            "Last Relevant Syslog:",
            f"{self.last_relevant_syslog}",
            "",
            "Assignment Group:",
            f"{self.assignment_group}",
            "",
            "Source:",
            f"{self.source}",
            "",
            "Fingerprint:",
            f"{self.fingerprint}",
            "--------------------------------------------------",
        ]
        return "\n".join(lines)

    def to_servicenow_table_api_dict(self) -> Dict[str, Any]:
        """Convert normalized payload to ServiceNow REST Table API record dictionary."""
        sys_priority = "3"
        if self.severity == "CRITICAL":
            sys_priority = "1"
        elif self.severity == "HIGH":
            sys_priority = "2"

        short_desc = f"[{self.severity}] {self.device_name} - {self.alert_name}"
        if self.affected_interface != "N/A":
            short_desc += f" (Int: {self.affected_interface})"

        desc = self.build_human_readable_description()

        record = {
            "short_description": short_desc,
            "description": desc,
            "caller_id": settings.SERVICENOW_CALLER_ID_SYS_ID,
            "u_device_name": self.device_name,
            "u_management_ip": self.management_ip,
            "u_site": self.site,
            "u_vendor_os": self.vendor_os,
            "u_alert_name": self.alert_name,
            "u_alert_fingerprint": self.fingerprint,
            "assignment_group": self.assignment_group,
            "priority": sys_priority,
            "contact_type": "monitoring",
            "state": "1" if self.state == "New" else "6" if self.state == "Resolved" else "2",
        }

        return record

    @classmethod
    def from_alertmanager_alert(
        cls,
        alert: Dict[str, Any],
        snmp_availability: str = "0",
        last_relevant_syslog: str = "No recent relevant syslog events found",
    ) -> "ServiceNowIncidentPayload":
        """Factory method constructing normalized payload from Alertmanager alert dictionary and evidence."""
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})

        device_name = labels.get("device_name", labels.get("instance", "unknown_device"))
        management_ip = labels.get("instance", "0.0.0.0")
        site = labels.get("site", "global")
        device_role = labels.get("device_role", "network_device")
        vendor_os = labels.get("vendor_os", "cisco_ios")

        alert_name = labels.get("alertname", "NetworkAlert")
        severity = labels.get("severity", "WARNING").upper()
        alert_status = alert.get("status", "firing").lower()
        problem_type = annotations.get("problem", "Network anomaly detected")
        recommended_action = annotations.get("action", "No specific action documented")

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        first_detected = alert.get("startsAt") or now

        # Alertmanager's webhook payload has no "updatedAt" field (that only exists on the
        # separate /api/v2/alerts query API). For a still-firing alert, "endsAt" is the Go
        # zero-value placeholder "0001-01-01T00:00:00Z", not a real time - use "now" instead.
        # Only a resolved alert's "endsAt" is a meaningful timestamp.
        if alert_status == "resolved" and alert.get("endsAt") and not alert["endsAt"].startswith("0001-01-01"):
            last_updated = alert["endsAt"]
        else:
            last_updated = now

        metric_value = annotations.get("summary", annotations.get("description", "SNMP metric threshold breached"))
        affected_interface = labels.get("ifIndex", "N/A")

        alert_group = f"{site}_{device_name}_{severity}"

        # Fingerprint calculation
        raw_key = f"{device_name}:{alert_name}:{affected_interface}"
        fingerprint = alert.get("fingerprint", hashlib.md5(raw_key.encode("utf-8")).hexdigest())

        # Assignment Group Resolution - routed by device_role metadata rather than
        # per-device hardcoding, so new devices route correctly without code changes.
        assignment_group = settings.resolve_assignment_group(device_role)

        priority = "3 - Moderate"
        if severity == "CRITICAL":
            priority = "1 - Critical"
        elif severity == "HIGH":
            priority = "2 - High"

        state = "Resolved" if alert_status == "resolved" else "New"
        res_reason = "Auto-Resolved by Monitoring" if alert_status == "resolved" else None
        res_notes = "Telemetry metrics returned to normal operating baseline." if alert_status == "resolved" else None

        return cls(
            device_name=device_name,
            management_ip=management_ip,
            site=site,
            device_role=device_role,
            vendor_os=vendor_os,
            alert_name=alert_name,
            severity=severity,
            alert_status=alert_status,
            problem_type=problem_type,
            recommended_action=recommended_action,
            first_detected=first_detected,
            last_updated=last_updated,
            snmp_availability=snmp_availability,
            last_relevant_syslog=last_relevant_syslog,
            metric_value=metric_value,
            affected_interface=affected_interface,
            alert_group=alert_group,
            fingerprint=fingerprint,
            assignment_group=assignment_group,
            priority=priority,
            source="Prometheus / Alertmanager",
            state=state,
            resolution_reason=res_reason,
            resolution_notes=res_notes,
        )
