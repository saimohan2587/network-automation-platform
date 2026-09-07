"""Alertmanager -> ServiceNow Webhook Receiver Endpoint.

Listens for incoming alert payloads from Prometheus Alertmanager, parses alert details,
queries Prometheus/Loki telemetry for evidence enrichment, and manages incident lifecycle.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path if needed
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from servicenow.config import settings
from servicenow.models.incident_payload import ServiceNowIncidentPayload
from servicenow.client.servicenow_client import ServiceNowClient
from servicenow.client.evidence_enricher import TelemetryEvidenceEnricher
from servicenow import maintenance as maintenance_mode

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("WebhookReceiver")

client = ServiceNowClient()
enricher = TelemetryEvidenceEnricher()


class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format % args))

    def _send_json_response(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_GET(self):
        if self.path in ("/", "/health", "/ready"):
            self._send_json_response(200, {
                "status": "healthy",
                "service": "servicenow_webhook_adapter",
                "mock_mode": client.mock_mode,
                "instance_url": client.instance_url
            })
        elif self.path == "/maintenance/status":
            state = maintenance_mode.status()
            self._send_json_response(200, {
                "enabled": state.enabled,
                "reason": state.reason,
                "enabled_at": state.enabled_at,
                "expires_at": state.expires_at,
                "scope_devices": state.scope_devices,
                "scope_sites": state.scope_sites,
                "grace_until": state.grace_until,
                "suppressed_count": state.suppressed_count,
                "history": state.history,
                "formatted": maintenance_mode.format_status(state),
            })
        else:
            self._send_json_response(404, {"error": "Endpoint not found"})

    def do_POST(self):
        if self.path in ("/maintenance/enable", "/maintenance/disable", "/maintenance/grace"):
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length) if content_length else b""
            try:
                body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except Exception as e:
                logger.error(f"Invalid JSON payload on {self.path}: {e}")
                self._send_json_response(400, {"error": "Invalid JSON format"})
                return

            try:
                if self.path == "/maintenance/enable":
                    state = maintenance_mode.enable(
                        reason=body.get("reason", ""),
                        duration=body.get("duration"),
                        devices=body.get("devices"),
                        sites=body.get("sites"),
                    )
                elif self.path == "/maintenance/disable":
                    state = maintenance_mode.disable(
                        apply_grace=body.get("apply_grace", True),
                        grace_seconds=body.get("grace_seconds"),
                    )
                else:  # /maintenance/grace
                    state = maintenance_mode.set_grace(seconds=body.get("duration_seconds"))

                self._send_json_response(200, {
                    "enabled": state.enabled,
                    "reason": state.reason,
                    "enabled_at": state.enabled_at,
                    "expires_at": state.expires_at,
                    "scope_devices": state.scope_devices,
                    "scope_sites": state.scope_sites,
                    "grace_until": state.grace_until,
                    "suppressed_count": state.suppressed_count,
                    "formatted": maintenance_mode.format_status(state),
                })
            except maintenance_mode.MaintenanceModeError as e:
                self._send_json_response(400, {"error": str(e)})
            return

        if self.path in ("/", "/webhook"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body.decode("utf-8"))
            except Exception as e:
                logger.error(f"Invalid JSON payload received: {e}")
                self._send_json_response(400, {"error": "Invalid JSON format"})
                return

            if isinstance(data, list):
                alerts = data
            elif isinstance(data, dict):
                alerts = data.get("alerts", [data] if "fingerprint" in data or "labels" in data else [])
            else:
                alerts = []

            logger.info(f"Received Alertmanager batch containing {len(alerts)} alert(s).")

            results = []
            for alert in alerts:
                try:
                    labels = alert.get("labels", {})
                    device_name = labels.get("device_name", labels.get("instance", "unknown_device"))
                    
                    # Fetch live evidence from Prometheus and Loki
                    snmp_avail = enricher.get_snmp_availability(device_name)
                    syslog_line = enricher.get_last_relevant_syslog(device_name)

                    payload = ServiceNowIncidentPayload.from_alertmanager_alert(
                        alert,
                        snmp_availability=snmp_avail,
                        last_relevant_syslog=syslog_line
                    )

                    action, inc_num = client.process_alert_payload(payload)
                    results.append({
                        "device": payload.device_name,
                        "alert": payload.alert_name,
                        "status": payload.alert_status,
                        "action": action,
                        "incident_number": inc_num,
                        "assignment_group": payload.assignment_group,
                        "fingerprint": payload.fingerprint
                    })
                except Exception as ex:
                    logger.error(f"Error processing alert item: {ex}", exc_info=True)
                    results.append({"error": str(ex)})

            self._send_json_response(200, {
                "status": "success",
                "processed_count": len(alerts),
                "results": results
            })
        else:
            self._send_json_response(404, {"error": "Endpoint not found"})


def run_server(host: str = settings.WEBHOOK_HOST, port: int = settings.WEBHOOK_PORT):
    server_address = (host, port)
    httpd = HTTPServer(server_address, WebhookHandler)
    logger.info(f"Starting ServiceNow Webhook Adapter Server on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping ServiceNow Webhook Server...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
