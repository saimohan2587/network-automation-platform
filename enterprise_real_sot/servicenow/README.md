# ServiceNow ITSM Network Automation Integration Module

## Overview
This module integrates Prometheus Alertmanager with ServiceNow ITSM for enterprise network monitoring. It normalizes telemetry alerts into standard ServiceNow incident records, enforces strict deduplication via alert fingerprints, and automates the incident lifecycle from initial firing to resolution.

---

## Data Contract Schema
Every incoming network alert is normalized into the following ServiceNow Incident Data Contract:

| Category | Datapoint | Field Name | Description |
| :--- | :--- | :--- | :--- |
| **Device** | Device Name | `device_name` | Hostname of network node (`R1_gns3`, `SW1_gns3`, etc.) |
| | Management IP | `management_ip` | IP address of target device |
| | Site | `site` | Geographical datacenter or branch location |
| | Device Role | `device_role` | Network role (`router`, `access_switch`, etc.) |
| | Vendor OS | `vendor_os` | Operating system (`cisco_ios`, `cisco_nxos`) |
| **Alert** | Alert Name | `alert_name` | Prometheus alert rule identifier |
| | Severity | `severity` | Severity level (`CRITICAL`, `HIGH`, `WARNING`) |
| | Alert Status | `alert_status` | Firing state (`firing` or `resolved`) |
| | Problem Type | `problem_type` | Short technical description of issue |
| **Timing** | First Detected | `first_detected` | ISO-8601 timestamp when alert started |
| | Last Updated | `last_updated` | Timestamp of latest evaluation/resolution |
| **Evidence** | Metric Value | `metric_value` | Diagnostic summary or threshold value |
| | Interface | `affected_interface` | Interface index/name (`ifIndex`), if applicable |
| **Correlation**| Alert Group | `alert_group` | Site + Device + Severity correlation group |
| | Fingerprint | `fingerprint` | Unique hash key for incident deduplication |
| **Ownership** | Assignment Group | `assignment_group` | Defaulted to `Network_Team` |
| | Priority | `priority` | `1 - Critical`, `2 - High`, or `3 - Moderate` |
| **Lifecycle** | State | `state` | `New`, `In Progress`, `Resolved`, `Closed` |

---

## Alertmanager Webhook Integration
Alertmanager routes all active receiver events to the webhook adapter endpoint:
`http://servicenow_adapter:8000/webhook`

### Configuration (`alertmanager.yml`)
```yaml
receivers:
  - name: 'network_team_critical'
    webhook_configs:
      - url: 'http://servicenow_adapter:8000/webhook'
        send_resolved: true
```

---

## ServiceNow Table API Credentials
Set the following environment variables in `.env` or container configuration:
```env
SERVICENOW_INSTANCE_URL=https://dev12345.service-now.com
SERVICENOW_USERNAME=api_network_user
SERVICENOW_PASSWORD=SecretPassword123
SERVICENOW_MOCK_MODE=false
```
*Note: If credentials are not set, the adapter safely operates in Mock / Staging Mode, storing incident records in `storage/incidents.json` without failing.*

---

## Incident Resolution Emails
When a device recovers, this module auto-resolves the incident by patching `state=6` (Resolved) via the Table API (see `_resolve_incident` in `client/servicenow_client.py`). This module itself never sends email — any resolution email came from the ServiceNow instance's own stock **"Incident resolved"** notification (`sys_notification`, condition `incident_stateCHANGESTO6`), which fires natively whenever any incident's state changes to Resolved.

That stock notification has been **deactivated** (`sys_id 942cb12e7ff9121073b72458bc866552`) on the configured instance to stop these recovery emails. Incidents still auto-resolve exactly as before (state, close notes, work notes); only the email is suppressed. To re-enable resolution emails, reactivate that notification record in ServiceNow under **System Notification > Notifications**.
