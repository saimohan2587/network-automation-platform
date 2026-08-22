# Enterprise Network Deployment Pipeline Documentation

## Pipeline Overview

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

## 1. Execution Modes

### A. Dry-Run Mode (`--dry-run`)
1. **Target Query (`DeviceSelector`)**: Queries NetBox REST API (`/api/dcim/devices/`) based on CLI filter criteria.
2. **Context Aggregation (`ContextBuilder`)**: Aggregates global, site, and device context data alongside interface details and IP assignments.
3. **Configuration Rendering (`ConfigGenerator`)**: Executes protocol plugins (AAA, VLAN, Port Security, STP, SNMP, NTP, DNS, Syslog, etc.), checking hardware interface existence (e.g. omitting non-existent NTP source interfaces).
4. **Pre-Deployment Validation (`PreDeploymentValidator`)**: Structural and rule-based validation verifies syntax, protocol dependencies, and interface parameters.
5. **Artifact Generation (`ArtifactManager`)**: Saves candidate `.cfg` files under `artifacts/pre_deployment/<timestamp>_<batch_name>/`.
6. **SSH Bypass**: SSH connection is bypassed.

### B. Live Deployment Mode (`--save-config`)
1. **Pre-Change Backup**: Downloads current `running-config` to `artifacts/deployments/<timestamp>/<device_name>/pre_change_running_config.txt`.
2. **Selective Change-Plan**: Compares candidate configuration line-by-line against `running-config`, categorizing items as `COMPLIANT` vs `CHANGE_REQUIRED`.
3. **SSH Push & Write Memory**: Sends `CHANGE_REQUIRED` commands to device via Netmiko and runs `write memory`.
4. **Automated Error Rollback**: Halts and executes inverse `no` commands if Cisco IOS rejects syntax.
5. **Post-Deployment Verification**: Runs `ComplianceOrchestrator` to verify actual switch state against NetBox intent.


## 2. Artifact Folder Structure

All pre-deployment dry-run artifacts are stored under `artifacts/pre_deployment/`:

```text
artifacts/
└── pre_deployment/
    ├── 20260805_101643_sw-access-01/
    │   ├── summary.txt
    │   └── sw-access-01.cfg
    ├── 20260805_103215_batch-3/
    │   ├── summary.txt
    │   ├── sw-access-01.cfg
    │   ├── sw-access-02.cfg
    │   └── sw-dist-01.cfg
    └── 20260806_090511_site-hyderabad/
        ├── summary.txt
        └── ...
```

---

## 3. How to Find Generated CLI Configurations

- Candidate CLI configurations are saved into individual `<device_name>.cfg` files inside the execution's artifact folder:
  ```text
  artifacts/pre_deployment/<timestamp>_<batch_name>/<device_name>.cfg
  ```
- **Candidates Only**: Only devices passing Pre-Deployment Assessment generate `.cfg` files.
- **Skipped Devices**: Devices failing assessment do **NOT** generate `.cfg` files. Their failure reasons are documented inside `summary.txt`.

---

## 4. How Timestamp Folders Work

- **Timestamp Format**: `YYYYMMDD_HHMMSS` (e.g., `20260805_103215`).
- **Batch Naming Rules**:
  - **Single Device**: `<timestamp>_<device_name>` (e.g., `20260805_101643_sw-access-01`)
  - **Multiple Devices**: `<timestamp>_batch-<count>` (e.g., `20260805_103215_batch-3`)
  - **Site Target**: `<timestamp>_<site_name>` (e.g., `20260806_090511_hyderabad`)
- **Execution Independence**:
  - Every run generates a new, independent timestamp folder.
  - Previous runs are **never overwritten** and **never deleted**.
  - A collision guard automatically appends indices (`_1`, `_2`) if multiple runs occur within the exact same second.

---

## 5. Difference Between Terminal Output & Generated Files

| Aspect | Terminal Output (`stdout`) | Generated Artifact Files (`artifacts/`) |
| :--- | :--- | :--- |
| **Purpose** | Concise operational status for CLI operators | Full audit record & device configuration state |
| **CLI Fragment Output** | **No long CLI dumps** printed to terminal | Full 203+ line Cisco IOS CLI stored in `<device_name>.cfg` |
| **Summary Content** | High-level counts, artifact path, and `.cfg` file list | Detailed metadata & device breakdown in `summary.txt` |
| **Skipped Devices** | Listed with failure reason under Skipped Devices | Listed with `SKIPPED` status & reason in `summary.txt` |

---

## 6. Example Commands

### Single Device Dry-Run with Interface Exclusion
```bash
python3 -m deployment.cli \
  --devices sw-access-01 \
  --protocols all \
  --exclude-interfaces GigabitEthernet3/0/1 \
  --dry-run
```

### Multi-Device Batch Dry-Run
```bash
python3 -m deployment.cli \
  --devices sw-access-01,sw-access-02,sw-dist-01 \
  --protocols all \
  --dry-run
```

### Live Deployment (Pushes CLI over SSH)
```bash
python3 -m deployment.cli \
  --devices sw-access-01 \
  --protocols all \
  --exclude-interfaces GigabitEthernet3/0/1
```
