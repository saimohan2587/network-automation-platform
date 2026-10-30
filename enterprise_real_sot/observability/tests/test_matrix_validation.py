"""Unit test verifying validity of Network Device Observability YAML configuration files."""

from pathlib import Path
import yaml


OBSERVABILITY_DIR = Path(__file__).resolve().parent.parent


def test_observability_config_yaml():
    config_file = OBSERVABILITY_DIR / "config" / "observability_config.yaml"
    assert config_file.exists(), f"Missing config file: {config_file}"
    with open(config_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "version" in data
    assert "severity_levels" in data
    assert "ownership_matrix" in data


def test_metric_matrix_yaml():
    metric_file = OBSERVABILITY_DIR / "metrics" / "metric_matrix.yaml"
    assert metric_file.exists(), f"Missing metric file: {metric_file}"
    with open(metric_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "metrics" in data
    assert len(data["metrics"]) >= 6, f"Expected at least 6 network device metrics, found {len(data['metrics'])}"


def test_event_matrix_yaml():
    event_file = OBSERVABILITY_DIR / "events" / "event_matrix.yaml"
    assert event_file.exists(), f"Missing event file: {event_file}"
    with open(event_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "events" in data
    assert len(data["events"]) >= 6, f"Expected at least 6 network device events, found {len(data['events'])}"


def test_alert_rules_yaml():
    alert_file = OBSERVABILITY_DIR / "alerts" / "alert_rules.yaml"
    assert alert_file.exists(), f"Missing alert file: {alert_file}"
    with open(alert_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "groups" in data
    assert len(data["groups"]) >= 1

    # Extract all alert rule names
    rules = [rule["alert"] for group in data["groups"] for rule in group.get("rules", [])]
    required_alerts = [
        "NetworkDeviceDown",
        "HighCpuUtilization",
        "HighMemoryUtilization",
        "InterfaceDown",
        "HighInterfaceErrors",
        "LinkFlapping",
    ]
    for required in required_alerts:
        assert required in rules, f"Missing Phase 3 required alert rule: {required}"


def test_alertmanager_yaml():
    am_file = OBSERVABILITY_DIR / "alertmanager" / "alertmanager.yml"
    assert am_file.exists(), f"Missing Alertmanager file: {am_file}"
    with open(am_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "route" in data, "Alertmanager missing route configuration"
    assert "inhibit_rules" in data, "Alertmanager missing inhibit_rules"
    assert "receivers" in data, "Alertmanager missing receivers"

    # Verify grouping fields
    group_by = data["route"].get("group_by", [])
    assert "site" in group_by, "Alertmanager grouping missing 'site'"
    assert "device_name" in group_by, "Alertmanager grouping missing 'device_name'"
    assert "severity" in group_by, "Alertmanager grouping missing 'severity'"


def test_docker_compose_phase4_hardening():
    compose_file = OBSERVABILITY_DIR / "docker-compose.yml"
    assert compose_file.exists(), f"Missing docker-compose file: {compose_file}"
    with open(compose_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "services" in data
    assert "volumes" in data

    services = data["services"]
    required_services = [
        "prometheus",
        "snmp_exporter",
        "loki",
        "promtail",
        "syslog_relay",
        "alertmanager",
        "grafana",
        "servicenow_adapter",
    ]
    for svc in required_services:
        assert svc in services, f"Missing required service: {svc}"
        assert "healthcheck" in services[svc], f"Service {svc} missing Phase 4 healthcheck"
        assert "deploy" in services[svc], f"Service {svc} missing Phase 4 resource limits"



def test_staging_and_prod_env():
    staging_file = OBSERVABILITY_DIR / "config" / "staging.env"
    prod_file = OBSERVABILITY_DIR / "config" / "production.env"
    assert staging_file.exists(), "Missing staging.env"
    assert prod_file.exists(), "Missing production.env"


def test_prometheus_yaml_valid_and_targets_present():
    prom_file = OBSERVABILITY_DIR / "prometheus" / "prometheus.yml"
    assert prom_file.exists(), f"Missing Prometheus config: {prom_file}"
    with open(prom_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "scrape_configs" in data
    assert "alerting" in data, "Prometheus must be wired to Alertmanager"

    snmp_job = next((j for j in data["scrape_configs"] if j.get("job_name") == "snmp_devices"), None)
    assert snmp_job is not None, "Missing the snmp_devices scrape job"
    device_names = {
        sc["labels"]["device_name"]
        for sc in snmp_job.get("static_configs", [])
        if "labels" in sc and "device_name" in sc["labels"]
    }
    for required in (
        "R1_gns3",
        "SW1_gns3",
        "SW2_gns3",
        "SW3Staging_gns3",
        "R2_gns3",
        "SW1Prod_gns3",
        "SW2Prod_gns3",
        "SW3Prod_gns3",
    ):
        assert required in device_names, f"Missing expected device target: {required}"


def test_alertmanager_webhook_and_send_resolved_consistency():
    """
    A wrong Alertmanager config can silently break the entire incident
    pipeline (this exact class of bug happened twice in this project's real
    history: send_resolved left at the wrong value after an unrelated fix).
    This test exists specifically to catch that regression in CI.
    """
    am_file = OBSERVABILITY_DIR / "alertmanager" / "alertmanager.yml"
    with open(am_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    receivers = data["receivers"]
    assert len(receivers) >= 1
    for receiver in receivers:
        webhook_configs = receiver.get("webhook_configs", [])
        assert webhook_configs, f"Receiver '{receiver['name']}' has no webhook_configs"
        for wc in webhook_configs:
            assert wc.get("url", "").endswith("/webhook"), (
                f"Receiver '{receiver['name']}' webhook URL does not point at the adapter's /webhook route: {wc.get('url')}"
            )
            assert wc.get("send_resolved") is True, (
                f"Receiver '{receiver['name']}' has send_resolved != true - resolved alerts would never reach "
                "ServiceNow and incidents would go stale. If this was intentionally disabled, suppress recovery "
                "emails via the ServiceNow notification rule instead (see docs/MAINTENANCE_MODE_IMPLEMENTATION_REPORT.md)."
            )

    # Severity-based routing must actually route CRITICAL/HIGH/WARNING somewhere.
    routes = data["route"].get("routes", [])
    routed_severities = set()
    for r in routes:
        for m in r.get("matchers", []):
            if m.startswith("severity"):
                routed_severities.add(m.split("=")[-1].strip().strip('"'))
    for required_severity in ("CRITICAL", "HIGH", "WARNING"):
        assert required_severity in routed_severities, f"No explicit route for severity={required_severity}"


def test_snmp_template_never_hardcodes_the_real_community_string():
    """
    Regression guard for the security-hardening fix: the checked-in template
    must contain the ${SNMP_COMMUNITY} placeholder, never a literal community
    value. The rendered snmp.yml (which DOES contain the real value) is
    git-ignored and intentionally not checked here.
    """
    template_file = OBSERVABILITY_DIR / "snmp_exporter" / "snmp.yml.template"
    assert template_file.exists(), "Missing observability/snmp_exporter/snmp.yml.template"
    text = template_file.read_text(encoding="utf-8")
    assert "${SNMP_COMMUNITY}" in text, "Template must use the ${SNMP_COMMUNITY} placeholder, not a literal value"
    assert "NOC-ReadOnly" not in text, "Found a literal community string in the TEMPLATE - it must only ever contain the placeholder"


ALL_TESTS = [
    test_observability_config_yaml,
    test_metric_matrix_yaml,
    test_event_matrix_yaml,
    test_alert_rules_yaml,
    test_alertmanager_yaml,
    test_docker_compose_phase4_hardening,
    test_staging_and_prod_env,
    test_prometheus_yaml_valid_and_targets_present,
    test_alertmanager_webhook_and_send_resolved_consistency,
    test_snmp_template_never_hardcodes_the_real_community_string,
]


if __name__ == "__main__":
    print("Running Network Device YAML matrix validation tests...")
    test_observability_config_yaml()
    print("✓ observability_config.yaml valid")
    test_metric_matrix_yaml()
    print("✓ metric_matrix.yaml valid")
    test_event_matrix_yaml()
    print("✓ event_matrix.yaml valid")
    test_alert_rules_yaml()
    print("✓ alert_rules.yaml valid")
    test_alertmanager_yaml()
    print("✓ alertmanager.yml valid")
    test_docker_compose_phase4_hardening()
    print("✓ docker-compose.yml Phase 4 hardening valid")
    test_staging_and_prod_env()
    print("✓ staging.env & production.env profiles valid")
    test_prometheus_yaml_valid_and_targets_present()
    print("✓ prometheus.yml valid, staging device targets present")
    test_alertmanager_webhook_and_send_resolved_consistency()
    print("✓ alertmanager.yml webhook routing + send_resolved consistency verified")
    test_snmp_template_never_hardcodes_the_real_community_string()
    print("✓ snmp.yml.template uses placeholder, not a literal community string")
    print("ALL NETWORK DEVICE OBSERVABILITY MATRICES & PHASE 4 CONFIGURATIONS PASSED VALIDATION SUCCESSFULLY!")


