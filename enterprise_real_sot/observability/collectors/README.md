# Observability Collectors Architecture

## Overview
This directory defines the telemetry collection architecture for the Network Hardware Fleet (R1_gns3, SW1_gns3, SW2_gns3).

## Collection Strategy: Out-of-Band Network Hardware Telemetry

### Out-of-Band Hardware Telemetry (Prometheus SNMP & Streaming Syslog)
- **Source Target Devices:** Network switches & routers (`10.10.10.2`, `10.10.20.2`, `10.10.30.2`).
- **Mechanism:** Continuous pull/poll by Prometheus SNMP Exporter and real-time Syslog ingestion via Syslog Relay (UDP 1514 / TCP 1515) to Loki.
- **Signals Handled:**
  - Device ICMP ping & SNMP reachability status (`up`)
  - Cisco CPU & RAM memory utilization (`cisco_cpu_utilization_percent`, `cisco_memory_used_bytes`)
  - Interface operational status (`ifOperStatus`), packet errors (`ifInErrors`/`ifOutErrors`), and link flapping syslogs

> **CRITICAL RULE:** Do NOT poll network hardware device metrics using Python SSH scripts inside deployment workflows. Hardware metrics MUST be collected out-of-band to guarantee scalability across the network fleet.

