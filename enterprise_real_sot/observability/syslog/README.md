# Cisco Network Syslog Relay & Ingestion Architecture

## Executive Summary
This directory contains the dedicated **Syslog Relay Service** (`syslog_relay.py`) for the enterprise network observability platform.

Standard Cisco IOS switches emit BSD-style syslog packets (**RFC 3164**, e.g., `<189>75: *Aug 31...`). Default Promtail syslog listeners strictly require **RFC 5424** formatting, causing unparsed log drops. The custom Python Syslog Relay acts as a high-performance socket listener and format adapter, normalizing Cisco logs and pushing structured JSON payloads directly to the Loki API (`http://loki:3100/loki/api/v1/push`).

---

## 1. Network Telemetry Architecture

```text
┌─────────────────────────────┐
│    GNS3 Cisco Devices       │ (sw2_gns3, sw1_gns3, r1_gns3)
│ (logging host 10.10.10.1)   │
└──────────────┬──────────────┘
               │ UDP 1514 / TCP 1515 (RFC 3164 BSD Syslog)
               ▼
┌─────────────────────────────┐
│  Syslog Relay Service       │ (Container: nac_observability_syslog_relay)
│  (syslog_relay.py)          │ • Multi-threaded UDP & TCP socket listener
│                             │ • Dynamic Cisco PRI priority & severity parser
│                             │ • Hostname extraction from origin-id / IP
└──────────────┬──────────────┘
               │ HTTP POST / JSON Payload
               ▼
┌─────────────────────────────┐
│  Loki Log Engine            │ (Container: nac_observability_loki)
│  (Persistent Storage)       │ • Stores logs in named volume `loki_data`
│                             │ • Indexes under `{job="syslog", hostname="..."}`
└──────────────┬──────────────┘
               │ LogQL Query
               ▼
┌─────────────────────────────┐
│  Grafana UI Dashboard       │ (Panel: Real-Time Cisco Syslog Stream)
└─────────────────────────────┘
```

---

## 2. Cisco Device Logging Configuration

To point any Cisco IOS device (router or switch) to the Syslog Relay:

```cisco
configure terminal
logging origin-id string <device_name>
logging trap debugging
logging host 10.10.10.1 transport udp port 1514
end
write memory
```

---

## 3. Log Labels & Metadata Mapping

Incoming log events are tagged in Loki with the following indexed labels:

| Label | Source | Example Value |
| :--- | :--- | :--- |
| `job` | Static | `syslog` |
| `hostname` | `logging origin-id` or IP fallback | `sw2_gns3`, `r1_gns3` |
| `source_ip` | Network socket address | `10.10.30.2` |
| `level` | Cisco Priority Severity calculation | `notice`, `error`, `info`, `warning` |
| `service_name` | Static | `syslog` |

---

## 4. Container Deployment & Execution

The service runs in Docker Compose (`docker-compose.yml`):

```yaml
  syslog_relay:
    image: python:3.11-alpine
    container_name: nac_observability_syslog_relay
    restart: unless-stopped
    ports:
      - "1514:1514/udp"
      - "1515:1515/tcp"
    volumes:
      - ./syslog/syslog_relay.py:/app/syslog_relay.py:ro
    command: python /app/syslog_relay.py --container
```
