# ABC Telecom Network Automation Platform

This project implements a Network-as-Code (NAC) architecture to manage the enterprise operational state in NetBox. 

## Deployment Pipeline & Dry-Run Artifacts

The deployment pipeline (`deployment/`) dynamically queries NetBox runtime Source of Truth, aggregates unified device context, renders multi-protocol Cisco IOS configurations, and validates changes prior to deployment.

### Quick Start Example

```bash
# Dry-run execution with interface exclusion
python3 -m deployment.cli \
  --devices sw-access-01 \
  --protocols all \
  --exclude-interfaces GigabitEthernet3/0/1 \
  --dry-run
```

### Dry-Run Artifact Storage

Every dry-run execution generates a unique timestamped folder under `artifacts/pre_deployment/`:

```text
artifacts/
└── pre_deployment/
    └── <timestamp>_<batch_name>/
        ├── summary.txt       # Human-readable batch assessment summary
        └── <device_name>.cfg # Rendered Cisco IOS CLI configuration for candidates
```

For full architecture and pipeline specifications, see [docs/DEPLOYMENT_FLOW.md](docs/DEPLOYMENT_FLOW.md).

---

## Coexisting Workflows

To support low-risk gradual migration, this repository supports two independent workflows:

### Workflow 1 (Legacy CSV Importer)
Reads network definitions from CSV tables and synchronizes them to NetBox:
```text
CSV Files (csv/) ──> Python Importer (python/) ──> NetBox (Operational SoT)
```

### Workflow 2 (New Git Intent Engine)
Reads structured configuration values, merges overrides, validates against schema specifications, and synchronizes state to NetBox:
```text
Git Intent YAMLs (intent/) ──> Python Parser ──> Schema Validation ──> NetBox
```

## Device Migration Engine

The `device_migration/` package provides dynamic, manifest-driven migration of operational configuration state from legacy access switches to new target devices. For full migration framework specifications, see [docs/DEVICE_MIGRATION.md](docs/DEVICE_MIGRATION.md).

```bash
# Discovery-only execution for migration manifest
python3 -m device_migration.cli --manifest config/migration/hyderabad_access_switches.yaml --discovery-only
```

---

## Directory Structure

* **`artifacts/`**: Pre-deployment dry-run configuration artifacts and migration dataset outputs.
* **`deployment/`**: Core 2-phase deployment orchestrator, protocol plugins, and transport drivers.
* **`device_migration/`**: Scalable device migration engine, dynamic mapping cascade, and artifact exporter.
* **`config/`**: Shared settings, credentials, and migration job manifests (`config/migration/`).
* **`csv/`**: Legacy CSV tables (DCIM, IPAM, and configuration contexts).
* **`python/`**: Legacy CSV import scripts.
* **`docs/`**: Design and operational documentation (`DEPLOYMENT_FLOW.md`, `DEVICE_MIGRATION.md`, etc.).
* **`scripts/`**: Automation helper scripts.

