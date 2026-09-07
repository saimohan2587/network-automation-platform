"""ServiceNow REST API Client & Incident Lifecycle Manager.

Handles API request execution against live ServiceNow Table API (/api/now/table/incident),
fingerprint deduplication, work notes updates, auto-resolution, and local state persistence.
"""

import json
import logging
import time
import urllib.request
import urllib.error
import base64
from typing import Dict, Any, Tuple, Optional
from pathlib import Path

from servicenow.config import settings
from servicenow.models.incident_payload import ServiceNowIncidentPayload
from servicenow import maintenance as maintenance_mode

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ServiceNowClient")


class ServiceNowClient:
    def __init__(self):
        self.instance_url = settings.SERVICENOW_INSTANCE_URL.rstrip("/")
        self.username = settings.SERVICENOW_USERNAME
        self.password = settings.SERVICENOW_PASSWORD
        self.timeout = settings.SERVICENOW_TIMEOUT
        self.mock_mode = settings.SERVICENOW_MOCK_MODE
        self.storage_file = settings.INCIDENT_STORE_FILE

        self._ensure_storage()

    def _ensure_storage(self):
        if not self.storage_file.exists():
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump({"active_incidents": {}, "incident_history": [], "counter": 100100}, f, indent=2)

    def _load_storage(self) -> Dict[str, Any]:
        try:
            with open(self.storage_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load incident storage file: {e}")
            return {"active_incidents": {}, "incident_history": [], "counter": 100100}

        if "active_incidents" not in data:
            # One-time migration from the old flat schema (single "incidents" dict keyed by
            # fingerprint, with no active/historical distinction - the root cause of resolved
            # incidents blocking a future outage from creating a new one).
            old_incidents = data.get("incidents", {})
            active, history = {}, []
            for fp, rec in old_incidents.items():
                rec.setdefault("fingerprint", fp)
                if rec.get("state") in ("Resolved", "Closed"):
                    history.append(rec)
                else:
                    active[fp] = rec
            data = {
                "active_incidents": active,
                "incident_history": history,
                "counter": data.get("counter", 100100),
            }
            logger.info(
                f"Migrated incident storage to active/history schema: "
                f"{len(active)} active, {len(history)} historical."
            )
            self._save_storage(data)

        data.setdefault("active_incidents", {})
        data.setdefault("incident_history", [])
        return data

    def _save_storage(self, data: Dict[str, Any]):
        try:
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save incident storage file: {e}")

    def _make_api_request(self, method: str, url: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Executes HTTP requests against ServiceNow REST API with Basic Auth."""
        req = urllib.request.Request(url, method=method.upper())
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        if self.username and self.password:
            auth_bytes = f"{self.username}:{self.password}".encode("utf-8")
            auth_str = base64.b64encode(auth_bytes).decode("utf-8")
            req.add_header("Authorization", f"Basic {auth_str}")

        body = json.dumps(data).encode("utf-8") if data else None
        try:
            with urllib.request.urlopen(req, data=body, timeout=self.timeout) as resp:
                raw_res = resp.read().decode("utf-8")
                return json.loads(raw_res) if raw_res else {}
        except urllib.error.HTTPError as http_err:
            error_body = http_err.read().decode("utf-8")
            logger.error(f"ServiceNow REST API HTTP Error {http_err.code}: {http_err.reason} - Body: {error_body}")
            err = RuntimeError(f"ServiceNow API HTTP {http_err.code}: {http_err.reason}")
            err.status_code = http_err.code
            raise err from http_err
        except Exception as err:
            logger.error(f"ServiceNow REST API Connection Error: {err}")
            raise

    def process_alert_payload(self, payload: ServiceNowIncidentPayload) -> Tuple[str, str]:
        """Main lifecycle router enforcing deduplication and state updates.

        Returns:
            Tuple[action_taken, incident_number]
        """
        # Maintenance Mode / Monitoring Suppression: checked ONLY for firing
        # alerts, before any create/update decision. Resolved alerts are never
        # suppressed here - a real, already-open incident must always be
        # allowed to close. Prometheus/Alertmanager/Grafana are unaffected by
        # this check; it only gates whether THIS process opens/touches a
        # ServiceNow ticket for the alert.
        if payload.alert_status == "firing":
            suppressed, suppression_reason = maintenance_mode.is_suppressed(
                device_name=payload.device_name, site=payload.site
            )
            if suppressed:
                logger.info(
                    "Alert '%s' for device '%s' suppressed: %s. No incident created or updated.",
                    payload.alert_name, payload.device_name, suppression_reason,
                )
                maintenance_mode.record_suppressed_event(payload.device_name, payload.alert_name, suppression_reason)
                return ("SUPPRESSED_MAINTENANCE", "N/A")

        store = self._load_storage()
        active_incidents = store["active_incidents"]
        fp = payload.fingerprint

        # Only an ACTIVE (unresolved) incident counts as "existing" for dedup purposes.
        # A resolved incident for this same fingerprint lives in incident_history and must
        # NOT block a new outage from creating a fresh incident.
        existing_inc = active_incidents.get(fp)

        # ----------------------------------------------------------------------
        # Scenario 1: Firing Alert & No Active Incident -> CREATE INCIDENT
        # ----------------------------------------------------------------------
        if payload.alert_status == "firing" and not existing_inc:
            inc_number = self._create_incident(payload, store)
            return ("CREATED", inc_number)

        # ----------------------------------------------------------------------
        # Scenario 2: Firing Alert & Active Incident Exists -> DEDUPLICATE / UPDATE
        # ----------------------------------------------------------------------
        elif payload.alert_status == "firing" and existing_inc:
            inc_number = existing_inc["incident_number"]
            logger.info(f"Duplicate alert received for fingerprint {fp}. Updating existing incident {inc_number}.")
            self._update_firing_incident(existing_inc, payload, store)
            return ("UPDATED_FIRING", inc_number)

        # ----------------------------------------------------------------------
        # Scenario 3: Resolved Alert & Active Incident Exists -> RESOLVE INCIDENT
        # ----------------------------------------------------------------------
        elif payload.alert_status == "resolved" and existing_inc:
            inc_number = existing_inc["incident_number"]
            logger.info(f"Alert resolved for fingerprint {fp}. Auto-resolving incident {inc_number}.")
            self._resolve_incident(existing_inc, payload, store)
            return ("RESOLVED", inc_number)

        # ----------------------------------------------------------------------
        # Scenario 4: Resolved Alert & No Active Incident -> IGNORE
        # ----------------------------------------------------------------------
        else:
            logger.info(f"Resolved alert received for unknown incident fingerprint {fp}. Skipping.")
            return ("IGNORED", "N/A")

    def _create_incident(self, payload: ServiceNowIncidentPayload, store: Dict[str, Any]) -> str:
        fp = payload.fingerprint

        if self.mock_mode:
            store["counter"] += 1
            inc_number = f"INC0{store['counter']}"
            sys_id = f"mock_sys_{store['counter']}"

            inc_record = {
                "sys_id": sys_id,
                "incident_number": inc_number,
                "fingerprint": fp,
                "device_name": payload.device_name,
                "management_ip": payload.management_ip,
                "site": payload.site,
                "alert_name": payload.alert_name,
                "severity": payload.severity,
                "state": "New",
                "first_detected": payload.first_detected,
                "last_updated": payload.last_updated,
                "updates_count": 1,
                "work_notes": [f"Incident created automatically from Alertmanager alert {payload.alert_name}."],
            }
            store["active_incidents"][fp] = inc_record
            self._save_storage(store)
            logger.info(f"[MOCK SERVICENOW] Created Incident {inc_number} for device {payload.device_name} (Fingerprint: {fp})")
            return inc_number
        else:
            url = f"{self.instance_url}/api/now/table/incident?sysparm_display_value=true"
            api_data = payload.to_servicenow_table_api_dict()

            try:
                response = self._make_api_request("POST", url, api_data)
                result = response.get("result", {})
                inc_number = result.get("number", "INC0000000")
                sys_id = result.get("sys_id", "")

                store["active_incidents"][fp] = {
                    "sys_id": sys_id,
                    "incident_number": inc_number,
                    "fingerprint": fp,
                    "device_name": payload.device_name,
                    "management_ip": payload.management_ip,
                    "site": payload.site,
                    "alert_name": payload.alert_name,
                    "severity": payload.severity,
                    "state": "New",
                    "first_detected": payload.first_detected,
                    "last_updated": payload.last_updated,
                    "updates_count": 1,
                    "work_notes": ["Incident created via ServiceNow Table API."],
                }
                self._save_storage(store)
                logger.info(f"[LIVE SERVICENOW PDI] Created REAL Incident {inc_number} (sys_id: {sys_id})")
                return inc_number
            except Exception as e:
                logger.error(f"Failed to post incident to live ServiceNow API: {e}")
                store["counter"] += 1
                inc_number = f"INC_RETRY_0{store['counter']}"
                store["active_incidents"][fp] = {
                    "sys_id": "pending_retry",
                    "incident_number": inc_number,
                    "fingerprint": fp,
                    "device_name": payload.device_name,
                    "alert_name": payload.alert_name,
                    "severity": payload.severity,
                    "state": "Pending_API_Retry",
                    "first_detected": payload.first_detected,
                    "last_updated": payload.last_updated,
                    "updates_count": 1,
                }
                self._save_storage(store)
                return inc_number

    def _update_firing_incident(self, inc_record: Dict[str, Any], payload: ServiceNowIncidentPayload, store: Dict[str, Any]):
        fp = payload.fingerprint
        inc_record["updates_count"] += 1
        inc_record["last_updated"] = payload.last_updated
        inc_record["state"] = "In Progress"
        note = f"Repeated alert firing at {payload.last_updated}. Summary: {payload.metric_value}"
        inc_record.setdefault("work_notes", []).append(note)

        sys_id = inc_record.get("sys_id", "")
        if not self.mock_mode:
            if sys_id.startswith("mock_sys_") or sys_id in ("pending_retry", ""):
                logger.info(f"Existing incident {inc_record['incident_number']} has mock sys_id. Creating real incident on ServiceNow PDI...")
                self._create_incident(payload, store)
                return

            url = f"{self.instance_url}/api/now/table/incident/{sys_id}"
            update_data = {"work_notes": note, "state": "2"}
            try:
                self._make_api_request("PATCH", url, update_data)
            except Exception as e:
                if getattr(e, "status_code", None) == 404:
                    logger.warning(
                        f"Incident {inc_record['incident_number']} (sys_id {sys_id}) no longer exists on "
                        f"ServiceNow PDI. Creating a replacement real incident..."
                    )
                    self._create_incident(payload, store)
                    return
                logger.error(f"Failed to patch work notes on live ServiceNow incident: {e}")
                store["active_incidents"][fp] = inc_record
                self._save_storage(store)
                return

        store["active_incidents"][fp] = inc_record
        self._save_storage(store)
        logger.info(f"[LIVE SERVICENOW PDI] Updated Incident {inc_record['incident_number']} (Update Count: {inc_record['updates_count']})")


    def _resolve_incident(self, inc_record: Dict[str, Any], payload: ServiceNowIncidentPayload, store: Dict[str, Any]):
        fp = payload.fingerprint
        inc_record["state"] = "Resolved"
        inc_record["last_updated"] = payload.last_updated
        inc_record["resolution_reason"] = payload.resolution_reason
        inc_record["resolution_notes"] = payload.resolution_notes

        note = f"Alert Auto-Resolved at {payload.last_updated}. Reason: {payload.resolution_reason}"
        inc_record.setdefault("work_notes", []).append(note)

        resolved_on_servicenow = self.mock_mode
        if not self.mock_mode and inc_record["sys_id"] not in ("pending_retry", ""):
            url = f"{self.instance_url}/api/now/table/incident/{inc_record['sys_id']}"
            resolve_data = {
                "state": "6",
                "close_code": "Solution provided",
                "close_notes": payload.resolution_notes or "Auto-Resolved by Monitoring System",
            }
            try:
                self._make_api_request("PATCH", url, resolve_data)
                resolved_on_servicenow = True
            except Exception as e:
                if getattr(e, "status_code", None) == 404:
                    logger.warning(
                        f"Incident {inc_record['incident_number']} (sys_id {inc_record['sys_id']}) no longer "
                        f"exists on ServiceNow PDI - nothing to resolve there. Clearing local record only."
                    )
                else:
                    logger.error(f"Failed to resolve live ServiceNow incident: {e}")

        # Move out of active_incidents into permanent history. This is what allows a future
        # occurrence of the same underlying alert (same fingerprint) to create a BRAND NEW
        # incident instead of reopening this one - the resolved incident stays as historical
        # evidence, but no longer blocks or gets reused by process_alert_payload's dedup check.
        store["active_incidents"].pop(fp, None)
        store["incident_history"].append(inc_record)
        self._save_storage(store)
        if resolved_on_servicenow:
            logger.info(f"[LIVE SERVICENOW PDI] Auto-Resolved Incident {inc_record['incident_number']}")
        else:
            logger.warning(f"Marked {inc_record['incident_number']} resolved locally only (ServiceNow PDI not updated).")

    def verify_incident_exists(self, sys_id_or_number: str) -> Optional[Dict[str, Any]]:
        """Queries live ServiceNow Table API to verify whether an incident record exists."""
        if self.mock_mode:
            logger.info("Mock mode active - Skipping live ServiceNow REST query.")
            return None

        if sys_id_or_number.startswith("INC"):
            url = f"{self.instance_url}/api/now/table/incident?sysparm_query=number={sys_id_or_number}&sysparm_limit=1"
        else:
            url = f"{self.instance_url}/api/now/table/incident/{sys_id_or_number}"

        try:
            res = self._make_api_request("GET", url)
            if "result" in res:
                result = res["result"]
                if isinstance(result, list) and len(result) > 0:
                    return result[0]
                elif isinstance(result, dict):
                    return result
            return None
        except Exception as e:
            logger.error(f"Failed to verify incident existence on ServiceNow PDI: {e}")
            return None
