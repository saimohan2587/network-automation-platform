# Enterprise Network Deployment Pipeline Documentation

## Pipeline Overview

```text
CLI Input (--dry-run)
    │
    ▼
DeviceSelector (NetBox API Query)
    │
    ▼
ContextBuilder (Build device_context from DCIM + Config Context)
    │
    ▼
ConfigGenerator (Render 15 Protocol Plugins; Exclude --exclude-interfaces)
    │
    ▼
PreDeploymentValidator (Structure & Protocol Safety Validation)
    │
    ├──► [PASS]  ──► Candidate -> Save <device_name>.cfg to Artifact Dir
    └──► [FAIL]  ──► Skipped   -> Record failure reason in summary.txt (NO .cfg generated)
    │
    ▼
ArtifactManager (Generate artifacts/pre_deployment/<timestamp>_<batch_name>/)
    ├── summary.txt (Batch statistics & pass/skipped device breakdown)
    └── <device_name>.cfg (Rendered Cisco IOS CLI for candidate devices)
    │
    ▼
Terminal Output (Concise summary of artifacts & candidate .cfg files)
```

---

## 1. Dry-Run Execution Flow

When executing the deployment engine with `--dry-run`:

1. **Target Query (`DeviceSelector`)**: Queries NetBox REST API (`/api/dcim/devices/`) based on CLI filter criteria.
2. **Context Aggregation (`ContextBuilder`)**: Aggregates global, site, and device context data alongside interface details and IP assignments.
3. **Configuration Rendering (`ConfigGenerator`)**: Executes up to 15 protocol plugins (AAA, VLAN, Port Security, STP, SNMP, NTP, DNS, Syslog, etc.), filtering out excluded ports specified via `--exclude-interfaces`.
4. **Pre-Deployment Validation (`PreDeploymentValidator`)**: Structural and rule-based validation verifies syntax, protocol dependencies, and interface parameters.
5. **Artifact Generation (`ArtifactManager`)**: Creates a timestamped artifact folder under `artifacts/pre_deployment/` and saves candidate `.cfg` files alongside `summary.txt`.
6. **SSH Bypass**: SSH connection establishment is skipped, preventing network modifications.

---

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
