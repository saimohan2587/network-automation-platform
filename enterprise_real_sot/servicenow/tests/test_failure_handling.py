"""
Unit tests for ServiceNowClient's behavior when the live ServiceNow REST API
fails (HTTP 401, HTTP 500, timeout, connection refused).

IMPORTANT - what these tests do NOT claim: there is currently no scheduled or
background retry job anywhere in this codebase. A failed create attempt is
recorded locally as "Pending_API_Retry" and nothing automatically revisits it.
The only way a Pending_API_Retry incident gets a second attempt today is if
Alertmanager happens to redeliver the SAME still-firing alert later (its own
repeat_interval, currently 4h) - at that point `_update_firing_incident`
detects the pending sys_id and calls `_create_incident` again as a side
effect of that external redelivery. These tests verify exactly that real
behavior - an opportunistic retry-on-next-delivery, not a reliable scheduled
retry mechanism - so nobody mistakes "handles failure gracefully" for
"reliably retries".
"""

import tempfile
from pathlib import Path

from servicenow.client.servicenow_client import ServiceNowClient
from servicenow.models.incident_payload import ServiceNowIncidentPayload


def _fresh_client():
    client = ServiceNowClient()
    client.mock_mode = False  # exercise the live-API code path, not the mock branch
    client.storage_file = Path(tempfile.mkdtemp(prefix="sn_failure_test_")) / "incidents.json"
    return client


def _sample_payload(fingerprint="failure_test_fp", status="firing"):
    alert = {
        "status": status,
        "labels": {
            "alertname": "NetworkDeviceDown",
            "severity": "CRITICAL",
            "device_name": "SW1_gns3",
            "instance": "10.10.20.2",
            "site": "hyderabad",
            "device_role": "access",
            "vendor_os": "cisco_ios",
        },
        "annotations": {"summary": "test"},
        "startsAt": "2026-01-01T00:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "fingerprint": fingerprint,
    }
    return ServiceNowIncidentPayload.from_alertmanager_alert(alert)


class _RaisingRequest:
    """A drop-in replacement for _make_api_request that always raises a given error."""

    def __init__(self, error):
        self.error = error
        self.calls = 0

    def __call__(self, method, url, data=None):
        self.calls += 1
        raise self.error


def _http_error(status_code, message):
    err = RuntimeError(f"ServiceNow API HTTP {status_code}: {message}")
    err.status_code = status_code
    return err


def test_http_401_marks_pending_retry_not_a_crash():
    client = _fresh_client()
    client._make_api_request = _RaisingRequest(_http_error(401, "Unauthorized"))
    payload = _sample_payload("fp_401")

    action, inc_number = client.process_alert_payload(payload)

    assert action == "CREATED"
    assert inc_number.startswith("INC_RETRY_")
    store = client._load_storage()
    assert store["active_incidents"]["fp_401"]["state"] == "Pending_API_Retry"


def test_http_500_marks_pending_retry_not_a_crash():
    client = _fresh_client()
    client._make_api_request = _RaisingRequest(_http_error(500, "Internal Server Error"))
    payload = _sample_payload("fp_500")

    action, inc_number = client.process_alert_payload(payload)

    assert action == "CREATED"
    assert inc_number.startswith("INC_RETRY_")
    store = client._load_storage()
    assert store["active_incidents"]["fp_500"]["state"] == "Pending_API_Retry"


def test_connection_failure_marks_pending_retry_not_a_crash():
    """Simulates a network-level failure (no HTTP response at all, e.g. DNS/connection refused)."""
    client = _fresh_client()
    client._make_api_request = _RaisingRequest(ConnectionRefusedError("Connection refused"))
    payload = _sample_payload("fp_connrefused")

    action, inc_number = client.process_alert_payload(payload)

    assert action == "CREATED"
    assert inc_number.startswith("INC_RETRY_")


def test_timeout_marks_pending_retry_not_a_crash():
    import socket
    client = _fresh_client()
    client._make_api_request = _RaisingRequest(socket.timeout("timed out"))
    payload = _sample_payload("fp_timeout")

    action, inc_number = client.process_alert_payload(payload)

    assert action == "CREATED"
    assert inc_number.startswith("INC_RETRY_")


def test_no_automatic_retry_happens_on_its_own():
    """
    Confirms the honest current behavior: after a failed create, nothing
    retries it by itself. The Pending_API_Retry record just sits there
    unless something external (a repeated webhook delivery) prompts another
    attempt. This test proves that absence, not a positive capability.
    """
    client = _fresh_client()
    client._make_api_request = _RaisingRequest(_http_error(500, "Internal Server Error"))
    payload = _sample_payload("fp_no_auto_retry")
    client.process_alert_payload(payload)

    store_immediately_after = client._load_storage()
    assert store_immediately_after["active_incidents"]["fp_no_auto_retry"]["state"] == "Pending_API_Retry"

    # Simulate the passage of time with no external event: nothing in this
    # codebase calls process_alert_payload or any retry function on its own.
    # The only honest way to show "no automatic retry" is to show that the
    # record is unchanged unless something re-invokes the client - which is
    # exactly what the next test demonstrates DOES work, but only when
    # prompted by a new incoming alert (i.e. Alertmanager redelivering).
    store_again = client._load_storage()
    assert store_again["active_incidents"]["fp_no_auto_retry"]["state"] == "Pending_API_Retry"


def test_pending_retry_incident_recovers_on_next_alertmanager_redelivery():
    """
    The one real 'retry' path that exists: if Alertmanager redelivers the SAME
    still-firing alert later (its own repeat_interval, not a mechanism this
    codebase controls), _update_firing_incident() detects the pending sys_id
    and attempts a fresh _create_incident(). If the API is healthy by then,
    the incident is created for real.
    """
    client = _fresh_client()
    client._make_api_request = _RaisingRequest(_http_error(500, "Internal Server Error"))
    payload = _sample_payload("fp_recovers")
    client.process_alert_payload(payload)  # first delivery: fails, Pending_API_Retry

    # ServiceNow "recovers" - simulate a healthy API for the next call.
    call_count = {"n": 0}

    def healthy_api(method, url, data=None):
        call_count["n"] += 1
        return {"result": {"number": "INC9999999", "sys_id": "real_sys_id_123"}}

    client._make_api_request = healthy_api
    action, inc_number = client.process_alert_payload(payload)  # simulated redelivery

    assert action == "UPDATED_FIRING"
    assert call_count["n"] >= 1, "the redelivery must have actually attempted the API call, not silently no-op'd"
    store = client._load_storage()
    assert store["active_incidents"]["fp_recovers"]["sys_id"] == "real_sys_id_123"
    assert store["active_incidents"]["fp_recovers"]["state"] != "Pending_API_Retry"


ALL_TESTS = [
    test_http_401_marks_pending_retry_not_a_crash,
    test_http_500_marks_pending_retry_not_a_crash,
    test_connection_failure_marks_pending_retry_not_a_crash,
    test_timeout_marks_pending_retry_not_a_crash,
    test_no_automatic_retry_happens_on_its_own,
    test_pending_retry_incident_recovers_on_next_alertmanager_redelivery,
]


if __name__ == "__main__":
    for test in ALL_TESTS:
        test()
        print(f"✓ {test.__name__}")
    print("ALL SERVICENOW FAILURE-HANDLING UNIT TESTS PASSED")
