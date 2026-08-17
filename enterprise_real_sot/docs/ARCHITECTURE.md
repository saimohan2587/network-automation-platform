# Architecture

## System Boundaries

NAC has two deliberately separate layers. The Import Layer establishes data in NetBox. The future Deployment Layer consumes NetBox data to configure devices. NetBox is the boundary between them.

```text
CSV source data
    ↓
Python Importers
    ↓
NetBox — Runtime Source of Truth
    ↓
Deployment Layer
    ↓
Cisco devices
```

The Deployment Layer must not read from `csv/`, infer intent from importer files, or depend on the Import Layer at runtime.

## Import Layer

The completed Import Layer is contained in `python/importers/` and is executed via `python3 python/importers/run_import.py`.

| Component | Responsibility |
| --- | --- |
| `common_api.py` | Shared NetBox REST session, URL construction, CRUD helpers, object resolution helpers, and import counters. |
| `import_dcim.py` | Imports DCIM hierarchy and inventory; enriches device local context, interface VLAN/LAG data, IPv6 assignments, and interface port-security custom fields. |
| `import_ipam.py` | Imports VLANs, prefixes, addresses, interface IP assignments, and primary IPv4 addresses. |
| `import_config_context.py` | Imports `Global-Defaults` and `Site-Defaults-<site>` configuration contexts from CSV data. |
| `python/importers/run_import.py` | Executes DCIM, IPAM, and configuration-context imports in dependency order, then validates representative imported objects. |

The important import sequence is: reference DCIM data first, then sites and physical placement, then devices and interfaces, followed by IPAM and configuration contexts. This preserves NetBox object dependencies.

## Deployment Layer

The `deployment/` package is the runtime integration boundary. Its existing `NetBoxClient`, `DeviceSelector`, and `ContextBuilder` components operate only through NetBox REST endpoints.

For each selected device, `ContextBuilder` merges:

```text
Global-Defaults → Site-Defaults-<site slug> → device.local_context_data
```

It then adds device identity, platform and role information, primary IPv4 address, interfaces, VLAN memberships, LAG relationships, interface custom fields, and assigned IP addresses. More-specific values override less-specific values during the dictionary merge.

The future portions of the Deployment Layer are configuration generation, protocol plugins, transport/connector implementations, and deployment orchestration. They must consume the unified context rather than re-querying CSV data.

## Repository Layout

```text
enterprise_real_sot/
├── config/                 # Importer settings
├── csv/                    # Completed Import Layer input
│   ├── dcim/               # Inventory and topology CSVs
│   ├── ipam/               # VLAN, prefix, and IP CSVs
│   └── config_context/     # Global, site, and device context CSVs
├── device_migration/       # Enterprise Device Migration package
├── python/importers/       # Completed NetBox import implementation (run_import.py)
├── deployment/             # Runtime NetBox access and deployment foundations
├── src/parser/             # YAML loader and merge engine utilities
├── ansible/                # Reserved automation integration area
├── scripts/                # Reserved helper-script area
├── tests/                  # Test area
├── docs/                   # Permanent project documentation
└── README.md               # Repository overview
```
`

`src/parser/` contains a YAML loader and merge engine intended for structured intent use. The current completed Import Layer uses the checked-in CSV hierarchy and config-context CSV files; do not alter that workflow when extending deployment capability.

## Runtime Execution Flow

1. A user or automation system submits a deployment request with NetBox-based selection criteria.
2. `NetBoxClient` queries NetBox and follows pagination until all matching records are retrieved.
3. `DeviceSelector` returns the targeted devices.
4. `ContextBuilder` creates one unified context per device.
5. Future generators and protocol plugins render deterministic Cisco configuration from that context.
6. A future connector applies approved configuration to Cisco devices and reports the result.

This separation supports horizontal scale: selection can return many devices, context creation is per-device, and protocol rendering can evolve independently of inventory import.
