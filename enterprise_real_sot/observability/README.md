# Enterprise Network-Only Observability Architecture

## Executive Summary
This document defines the dedicated **Network Device Observability Architecture** for the enterprise Network Automation Platform (NAC). 

Observability in this stack is strictly isolated to **network device telemetry** (R1_gns3, SW1_gns3, SW2_gns3) and operates completely decoupled from the core Network-as-Code (NAC) deployment pipeline.

---

## 1. Network Telemetry Architecture Flow

```
+------------------------------------+
|        GNS3 Network Devices        |
|    (R1_gns3, SW1_gns3, SW2_gns3)   |
+------------------------------------+
                  |
        +---------+---------+
        |                   |
   SNMP Metrics       Syslog Events
   (Port 161)         (UDP 1514 / TCP 1515)
        |                   |
        v                   v
+---------------+   +-------------------+
| SNMP Exporter |   |   Syslog Relay    |
|  (Port 9116)  |   | (UDP 1514/TCP1515)|
+---------------+   +-------------------+
        |                   |
        v                   v
+---------------+   +-------------------+
|  Prometheus   |   |   Loki (Storage)  |
|  (Port 9090)  |   | (Port 3100 + Vol) |
+---------------+   +-------------------+
        |                   |
        +---------+---------+
                  |
                  v
       +--------------------+
       | Grafana Dashboard  |
       |    (Port 3000)     |
       +--------------------+
                  |
                  v
       +--------------------+
       |    Alertmanager    |
       |    (Port 9093)     |
       +--------------------+
```

---

## 2. Monitored Network Signals & Telemetry Matrix

| Signal | Source | Metrics / Query | Alert Trigger Condition | Severity |
|---|---|---|---|---|
| **Device UP/DOWN** | SNMP Exporter | `up{job="snmp_devices"}` | `up{job="snmp_devices"} == 0` for 2m | CRITICAL |
| **CPU Utilization** | SNMP (CISCO-PROCESS-MIB) | `cisco_cpu_utilization_percent` | `cisco_cpu_utilization_percent > 85` for 5m | WARNING |
| **Memory Utilization** | SNMP (CISCO-MEMORY-POOL-MIB) | `cisco_memory_used_bytes / ... * 100` | `memory_percent > 90` for 5m | WARNING |
| **Interface Status** | SNMP (IF-MIB :: ifOperStatus) | `ifOperStatus` | `ifOperStatus{admin_status="UP"} == 2` for 1m | HIGH |
| **Interface Errors** | SNMP (IF-MIB :: ifInErrors/ifOutErrors) | `rate(ifInErrors[5m]) + rate(ifOutErrors[5m])` | `error_rate > 10` for 3m | WARNING |
| **Link Flapping** | Syslog Event Collector | `{job="syslog"}` | `increase(interface_flaps[10m]) >= 5` | HIGH |
| **Device Syslogs** | Syslog Collector / Loki | `{job="syslog"}` | Real-time log stream | INFO |

---

## 3. Target Devices Configuration

- **R1_gns3** (`10.10.10.2`): Router (Cisco IOS)
- **SW1_gns3** (`10.10.20.2`): Access Switch (Cisco IOS)
- **SW2_gns3** (`10.10.30.2`): Access Switch (Cisco IOS)

---

## 4. Operational Container Services (`docker-compose.yml`)

1. **Prometheus** (`:9090`): Collects SNMP metrics from SNMP Exporter.
2. **SNMP Exporter** (`:9116`): Polls Cisco SNMP MIBs from GNS3 network devices.
3. **Loki** (`:3100`): Stores real-time syslog events permanently via Docker volume (`loki_data`).
4. **Syslog Relay** (`:1514` UDP / `:1515` TCP): Ingests Cisco BSD (RFC 3164) & RFC 5424 syslog streams and pushes structured logs to Loki under `{job="syslog"}`.
5. **Promtail** (`:9080`): Internal agent & log collector.
6. **Grafana** (`:3000`): Visualizes real-time metrics and syslog streams on the Network Devices Dashboard.
7. **Alertmanager** (`:9093`): Manages alert evaluation, deduplication, and notifications.

---

## 5. Architectural Decoupling Rule

The observability infrastructure runs in complete isolation from the NAC deployment core:
- The core deployment pipeline (`deployment/main.py`) and compliance suite (`post_deployment_validation/main.py`) contain ZERO telemetry or logging dependencies.
- Network device monitoring relies strictly on hardware SNMP MIB polling and Syslog UDP streams.
