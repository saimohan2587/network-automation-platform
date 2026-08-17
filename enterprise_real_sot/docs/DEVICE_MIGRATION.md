# Enterprise Device Migration Framework (`device_migration`)

The `device_migration` package automates the discovery, extraction, normalization, and hardware-mapped translation of switch configurations from legacy source devices (`sw-access-01`) to newly integrated target devices (`sw-access-07`).

---

## 1. Key Features & Guarantees

- **Scalable Batch Processing**: Handles 1 to 100+ migration pairs driven by external declarative YAML manifests.
- **Zero-Code Modifications**: Device names, management IPs, and interface mapping regex rules are completely externalized into YAML manifest files.
- **Fault Isolation**: Migration pairs execute inside isolated error boundaries (`try...except`). A failure on 1 pair will not halt the remaining pairs in a batch.
- **Read-Only Discovery (Phase 1)**: Operational state is collected strictly over SSH using `SSHCollector` and parsed using existing resource validation plugins (`ResourceRegistry`).
- **Management SVI Protection**: Target management IPs (e.g. `192.168.1.2/24` on `Vlan1`) and SSH credentials are strictly preserved.

---

## 2. Directory Structure

```text
enterprise_real_sot/
├── config/
│   └── migration/
│       └── hyderabad_access_switches.yaml    # External declarative migration manifest
├── device_migration/                          # Core Enterprise Package
│   ├── __init__.py
│   ├── cli.py                                 # Command-line interface entrypoint
│   ├── main.py                                # MigrationOrchestrator engine
│   ├── manifest_loader.py                     # YAML/JSON manifest loader & validator
│   ├── interface_mapper.py                    # Hardware interface mapping engine
│   ├── parser_engine.py                       # Adapter wrapping compliance resource plugins
│   ├── collector.py                           # Read-only SSH collector wrapper
│   ├── artifact_manager.py                    # JSON artifact exporter
│   └── logger.py                              # Structured logging module
└── artifacts/
    └── migration/                             # Per-pair output artifacts
        └── sw-access-01_to_sw-access-07/
            ├── summary.json
            ├── migration_dataset.json
            ├── interface_mapping.json
            └── raw_outputs.json
```

---

## 3. Migration Manifest Format (`config/migration/*.yaml`)

```yaml
metadata:
  manifest_version: "1.0"
  batch_name: "hyderabad_access_switch_refresh"
  description: "Enterprise migration of legacy Cisco 3750 Stack switches to standalone 3750X units"

default_rules:
  preserve_target_mgmt_ip: true
  target_mgmt_interface: "Vlan1"
  pattern_mappings:
    - name: "Access Ports (Module 3 to Module 1)"
      regex: "^(?:GigabitEthernet|Gi)3/0/(\\d+)$"
      replacement: "GigabitEthernet1/0/\\1"
    - name: "10G SFP+ Uplinks"
      regex: "^(?:TenGigabitEthernet|Te)3/1/(\\d+)$"
      replacement: "TenGigabitEthernet1/1/\\1"
    - name: "1G SFP Uplinks"
      regex: "^(?:GigabitEthernet|Gi)3/1/(\\d+)$"
      replacement: "GigabitEthernet1/1/\\1"
    - name: "Out-of-band Management"
      regex: "^(?:FastEthernet|Fa)0$"
      replacement: "FastEthernet0"
    - name: "Management SVI"
      regex: "^(?:Vlan100|vlan100|Vlan1|vlan1)$"
      replacement: "Vlan1"

migration_pairs:
  - source_device: "sw-access-01"
    target_device: "sw-access-07"
    site: "hyderabad"
    enabled: true
    override_interface_mappings: {}
```

---

## 4. CLI Execution Reference

### Run Read-Only Discovery (Phase 1)
```bash
python3 -m device_migration.cli --manifest config/migration/hyderabad_access_switches.yaml --discovery-only
```

### CLI Flags
- `--manifest <path>`: Required path to external YAML/JSON migration manifest file.
- `--discovery-only`: Execute read-only discovery, normalization, and artifact export without modifying NetBox or network switches.
