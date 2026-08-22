# Continuous Deployment (CD) Pipeline Architecture & Design (`CD_DESIGN.md`)

## Executive Summary

The Enterprise Network Automation Platform Continuous Deployment (CD) pipeline orchestrates automated configuration delivery from NetBox REST API (Runtime Source of Truth) to multi-role physical and virtual Cisco network devices.

The pipeline enforces **fail-fast gatekeeper isolation**, **selective change-plan deployment**, **automated inverse-command rollback**, and **post-deployment compliance verification** without impacting non-target or non-faulty devices.

---

## 1. High-Level CD Pipeline Architecture

```text
CSV / Git Intent Repository
       │
       ▼
[ Stage 0: Automated Pre-Sync ] 
   Import_config_context.py → NetBox REST API = Runtime Source of Truth
       │
       ▼
[ Stage 1: Context Aggregation ] 
   ContextBuilder aggregates Global < Site < Device Context < Local Interfaces via REST API
       │
       ▼
[ Stage 2: Capability & Protocol Filtering ]
   CapabilityResolver filters non-supported protocols for device role (e.g. L3 routing on L2 switch)
       │
       ▼
[ Stage 3: Candidate CLI Generation & Pre-Validation ]
   ConfigGenerator renders candidate .cfg in artifacts/pre_deployment/
       │
       ▼
[ Stage 4: Pre-Change Backup & Selective SSH Deployment ]
   • Netmiko SSH connection established
   • Downloads running-config to artifacts/deployments/
   • Evaluates Change Plan (COMPLIANT vs CHANGE_REQUIRED)
   • Pushes only CHANGE_REQUIRED commands
   • Executes 'write memory' (save-config)
       │
       ▼
[ Stage 5: Automated Inverse Rollback (If Error Occurs) ]
   • If Cisco IOS returns '% Invalid input', deployment halts instantly
   • Generates & executes precise inverse ('no') commands
   • Marks state: ROLLBACK_SUCCESSFUL
       │
       ▼
[ Stage 6: Post-Deployment Compliance Validation ]
   • ComplianceOrchestrator connects via SSH
   • Executes read-only 'show' commands (CollectorFactory)
   • StateComparator evaluates NetBox Expected vs Switch Actual
   • Saves report to artifacts/post_deployment/ (COMPLIANT / DRIFT / FAILED)
```

---

## 2. Detailed Stage Breakdown

### Stage 0: Automated Intent Pre-Sync
* **Objective**: Ensure NetBox REST API reflects the latest Git/CSV managed intent before runtime querying.
* **Component**: `python/importers/import_config_context.py`
* **Behavior**: Ingests CSV files (`csv/config_context/`) and uploads Global, Site, and Device-specific configuration contexts into NetBox REST API.

### Stage 1: Runtime Context Aggregation
* **Objective**: Construct a unified, hierarchical device context in memory.
* **Component**: `deployment/context_builder.py`
* **Hierarchy**: `Global Context < Site Context < Device-Specific Context < Local Interface Metadata`
* **Feature**: Queries NetBox REST API endpoints (`/api/extras/config-contexts/`, `/api/dcim/interfaces/`, `/api/ipam/ip-addresses/`).

### Stage 2: Capability & Role Filtering
* **Objective**: Enforce strict hardware role isolation to prevent illegal protocol generation.
* **Component**: `deployment/capability_resolver.py`
* **Rules**:
  * `gateway-router` (`R1_gns3`) -> `{BASE_INTERFACE, LAYER3_ROUTING, GLOBAL_MANAGEMENT}`
  * `layer-2-access-switch` (`SW1_gns3`) -> `{BASE_INTERFACE, LAYER2_SWITCHING, GLOBAL_MANAGEMENT}`

### Stage 3: Candidate CLI Generation & Pre-Deployment Validation
* **Objective**: Render Cisco IOS CLI and validate against structural rules.
* **Components**: `deployment/config_generator.py` & `pre_deployment_validation/orchestrator.py`
* **Features**:
  * Validates hardware interface references (e.g., skips `ntp source FastEthernet0/0` if `FastEthernet0/0` does not exist on target switch).
  * If validation fails (`SEVERITY_ERROR`), Gatekeeper marks device `ASSESSMENT_FAILED`, **0 commands sent**, SSH skipped.

### Stage 4: Pre-Change Backup & Selective SSH Deployment
* **Objective**: Safely deliver configuration changes over SSH.
* **Component**: `deployment/device_connector.py` (Netmiko transport)
* **Steps**:
  1. Captures pre-change `running-config` to `artifacts/deployments/<timestamp>/<device>/pre_change_running_config.txt`.
  2. Compares candidate configuration line-by-line against `running-config`.
  3. Pushes **only** missing/changed commands (`CHANGE_REQUIRED`).
  4. Executes `write memory` (`save-config`).

### Stage 5: Automated Inverse-Command Rollback
* **Objective**: Guarantee zero-outage safety if Cisco IOS rejects syntax.
* **Behavior**: If Cisco IOS stream returns `% Invalid input detected at '^' marker.`, deployment halts instantly, constructs exact inverse (`no`) commands for sent payload, executes them, and logs state as `ROLLBACK_SUCCESSFUL`.

### Stage 6: Post-Deployment Compliance Validation
* **Objective**: Independently audit switch state after change execution.
* **Component**: `post_deployment_validation/main.py` (`ComplianceOrchestrator`)
* **Behavior**: Connects via SSH, runs read-only `show` commands (`show vlan brief`, `show spanning-tree summary`, `show hosts`), and compares NetBox desired state against actual switch state.

---

## 3. Supported Multi-Role Device Matrix

| Device Name | Platform Slug | Role | Management IP | Active Protocols |
| :--- | :--- | :--- | :--- | :--- |
| **`R1_gns3`** | `cisco_ios` | `gateway-router` | `10.10.10.1` | `interface_base`, `routing`, `dns`, `syslog`, `snmp`, `ntp` |
| **`SW1_gns3`** | `cisco_ios` | `layer-2-access-switch` | `10.10.20.2` | `interface_base`, `vlan`, `stp`, `cdp`, `dns`, `syslog`, `snmp` |

---

## 4. CLI Execution Reference

### Dry-Run Execution
```bash
python3 -m deployment.cli --devices SW1_gns3 --dry-run
```

### Live Deployment Execution
```bash
python3 -m deployment.cli --devices SW1_gns3 --save-config
```

### Run Static CI Test Suite
```bash
python3 tests/ci_runner.py
```
