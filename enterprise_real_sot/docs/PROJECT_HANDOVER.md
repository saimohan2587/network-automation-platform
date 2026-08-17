# Network-as-Code (NAC) Enterprise SOT — Complete Technical Project Handover Document

> **Document Classification**: Technical Architecture & Operations Manual  
> **Target Audience**: Network Automation Engineers, LLM AI Assistants (ChatGPT / Codex / Gemini), Systems Administrators  
> **Repository Name**: `enterprise_real_sot`  
> **Primary Maintainer Scope**: NetBox Source of Truth, Generic Deployment Pipeline, Read-Only Compliance & Config Drift Engine

---

## 1. Project Overview

### What Problem This Project Solves
In traditional enterprise network engineering, device configurations are frequently modified manually via SSH terminal sessions (`configure terminal`). This leads to configuration drift, unauthorized changes, lack of auditability, and inconsistent device states across sites. 

This project implements a **Network-as-Code (NAC)** architecture where **NetBox** acts as the single runtime **Source of Truth (SoT)** for all network intent. Manual device changes are eliminated. All configuration changes originate in NetBox and are programmatically generated and deployed to physical network hardware through automated, generic pipelines.

### Why This Project Exists
1. **Decouple Intent from Hardware**: Network configuration policies are stored as structured intent in NetBox rather than raw text files or manual switch CLI commands.
2. **Generic & Dynamic Deployment**: Eliminates writing device-specific Python scripts. The deployment pipeline dynamically targets devices, resolves SSH credentials, renders cisco CLI templates, and deploys changes.
3. **Safety-First Audit Gates**: Supports `--dry-run` modes to simulate CLI generation without touching live devices.
4. **Environment-Based Credential Isolation**: Removes secrets (passwords, enable secrets) from NetBox and source code by dynamically resolving credentials from a local, Git-ignored `.env` file at runtime.
5. **Continuous Read-Only Drift Detection**: Provides an independent Compliance Layer that compares NetBox (Desired State) against physical network switches (Actual State) without modifying NetBox or running configuration commands on network devices.

### Current Scope
- **Import Layer**: CSV-driven population of NetBox DCIM inventory, IPAM subnetting/IP assignments, and Global/Site configuration contexts.
- **Deployment Layer**: Dynamic device selection, 3-tier context aggregation, dynamic credential mapping, plugin-based CLI rendering, and Netmiko SSH deployment.
- **Compliance Layer**: Read-Only SSH actual state collection, dynamic resource plugin discovery, generic recursive dictionary state comparison, and CLI drift reporting.
- **Protocol POC Scope**: **Port Security** protocol implemented end-to-end across physical switch `sw-access-01`.

### Current Limitations
- Currently tested against Cisco IOS / IOS-XE access switches (`cisco_ios` Netmiko driver).
- Concrete protocol plugins currently implemented: `port_security`.
- Data collection transport currently implemented: Read-only SSH (`SSHCollector`).

### What Is Already Completed
- [x] Automated NetBox Importer (`python/importers/`) for DCIM, IPAM, and Config Contexts.
- [x] Unified 3-Tier `ContextBuilder` (Global-Defaults → Site-Defaults → Device Local Context).
- [x] Environment Credential Resolver (`deployment/credentials.py` reading `.env`).
- [x] Generic Deployment CLI (`deployment/cli.py`) with `--dry-run` and `--save-config` flags.
- [x] Plugin-based `ConfigGenerator` (`deployment/config_generator.py` & `PortSecurityProtocol`).
- [x] Netmiko SSH `DeviceConnector` (`deployment/device_connector.py`).
- [x] Generic Compliance CLI (`compliance/cli.py`).
- [x] Read-only `SSHCollector` (`compliance/collectors/ssh_collector.py`).
- [x] Dynamic `ResourceRegistry` (`compliance/resources/registry.py`).
- [x] Protocol-Agnostic `StateComparator` (`compliance/comparator.py`).
- [x] Structured `ComplianceReporter` (`compliance/report.py`).

### Future Scope
- Additional Deployment & Compliance Protocol Plugins (`OSPF`, `BGP`, `VLAN`, `STP`, `NTP`, `DHCP Snooping`, `WLAN`).
- Additional Transport Collectors (`RESTCollector` for WLCs/AP controllers, `NetconfCollector`).
- Automated Drift Remediation Workflow (Admin-approved push from NetBox).

---

## 2. Repository Structure

```text
enterprise_real_sot/
├── config/                     # Importer environment & NetBox connection settings
│   └── settings.py             # NetBox API URL, API Token, logging levels
├── csv/                        # Source CSV files used by Import Layer
│   ├── config_context/         # Global and site-level configuration context CSVs
│   ├── dcim/                   # Inventory, sites, racks, devices, interfaces CSVs
│   └── ipam/                   # VLANs, prefixes, IP addresses CSVs
├── python/importers/           # NetBox REST API import engine
│   ├── common_api.py           # Shared NetBox REST session & CRUD helpers
│   ├── import_config_context.py# Imports Global & Site config contexts
│   ├── import_dcim.py          # Imports DCIM inventory, devices, interfaces, custom fields
│   ├── import_ipam.py          # Imports VLANs, subnets, IP assignments, primary IPv4
│   └── run_import.py           # Import orchestrator & validation runner
├── deployment/                 # Network-as-Code Deployment Pipeline
│   ├── __init__.py             # Package init
│   ├── cli.py                  # CLI entry point (python -m deployment.cli)
│   ├── config.py               # Environment configuration loader (.env)
│   ├── config_generator.py     # Configuration renderer engine & plugin loader
│   ├── context_builder.py      # Merges 3-tier NetBox configuration context
│   ├── credentials.py          # Dynamic management IP & SSH profile credential resolver
│   ├── device_connector.py     # Netmiko SSH transport deployment connector
│   ├── device_selector.py      # Dynamic NetBox device selector
│   ├── logger.py               # Deployment logger utility
│   ├── main.py                 # Deployment pipeline orchestrator
│   ├── netbox_client.py        # Generic NetBox REST API client
│   ├── utils.py                # Dictionary deep merge utilities
│   └── protocols/              # Deployment protocol plugins
│       ├── base_protocol.py    # Abstract BaseProtocol contract
│       └── port_security.py    # Port Security deployment plugin
├── compliance/                 # Network-as-Code Read-Only Compliance Layer
│   ├── __init__.py             # Package init
│   ├── cli.py                  # Compliance CLI entry point (python -m compliance.cli)
│   ├── comparator.py           # Protocol-agnostic recursive dictionary comparator
│   ├── logger.py               # Compliance logger utility
│   ├── main.py                 # Compliance pipeline orchestrator
│   ├── report.py               # Result dataclasses & ASCII report formatter
│   ├── collectors/             # Data collection transports
│   │   ├── __init__.py         # Collectors package init
│   │   ├── base_collector.py   # Abstract BaseCollector contract
│   │   ├── factory.py          # Transport collector factory
│   │   └── ssh_collector.py    # Read-only Netmiko SSH collector
│   └── resources/              # Compliance resource plugins
│       ├── __init__.py         # Resources package init
│       ├── base_resource.py    # Abstract BaseResource contract
│       ├── port_security.py    # Port Security compliance plugin
│       └── registry.py         # Dynamic plugin discovery registry
├── docs/                       # Project architecture & handover documentation
├── .env                        # Local credentials & secrets (GIT-IGNORED)
├── .env.example                # Sample environment configuration template
├── .gitignore                  # Git ignore definitions
├── run_import.py               # Root wrapper script for running NetBox importer
└── README.md                   # Repository overview
```

### Folder Responsibilities Table

| Folder Path | Need | Purpose | Responsible For |
| --- | --- | --- | --- |
| `config/` | System Configuration | Defines runtime API settings for NetBox importers. | `settings.py` loads `NETBOX_URL`, `NETBOX_TOKEN`, timeouts. |
| `csv/` | Source Data | Contains baseline static network intent in tabular CSV format. | Input data for NetBox Importer (`dcim/`, `ipam/`, `config_context/`). |
| `python/importers/` | Data Ingestion | Populates local/remote NetBox instance from CSV files. | Creates NetBox DCIM objects, IPAM subnets, custom fields, and config contexts. |
| `deployment/` | Change Execution | Generates and pushes CLI configurations to physical network hardware. | Queries NetBox, aggregates context, resolves secrets, renders CLI, executes SSH push. |
| `deployment/protocols/` | Deployment Extensibility | Defines protocol-specific configuration generators. | Implements `BaseProtocol` plugins (e.g. `port_security.py`). |
| `compliance/` | Audit & Drift | Measures drift between NetBox (Desired) and Switches (Actual). | Executes read-only SSH `show` commands, normalizes actual state, compares states. |
| `compliance/resources/` | Compliance Extensibility | Defines resource-specific parsing and state extraction. | Implements `BaseResource` plugins (e.g. `port_security.py`). |
| `compliance/collectors/` | Data Collection | Decouples connection transport from parsing logic. | Read-only SSH execution over Netmiko (`SSHCollector`). |

---

## 3. End-to-End Architecture

```text
========================================================================================
                                DEPLOYMENT PIPELINE
========================================================================================

                  User CLI Command: python -m deployment.cli
                                      │
                                      ▼
                           DeploymentOrchestrator
                                      │
       ┌──────────────────────────────┼──────────────────────────────┐
       ▼                              ▼                              ▼
DeviceSelector                 ContextBuilder                CredentialResolver
       │                              │                              │
       ▼ (REST API)                   ▼ (REST API)                   ▼ (.env File)
NetBox SoT (Query Devices)    NetBox SoT (Fetch Context)     SSH Profile Creds
       │                              │                              │
       └──────────────────────────────┼──────────────────────────────┘
                                      ▼
                               ConfigGenerator
                                      │
                                      ▼
                         Protocol Plugin (port_security)
                                      │ (Generates Cisco CLI commands)
                                      ▼
                         DeviceConnector (Netmiko SSH)
                                      │ (Pushes CLI in Config Mode)
                                      ▼
                           Physical Network Switch

========================================================================================
                                COMPLIANCE PIPELINE
========================================================================================

                  User CLI Command: python -m compliance.cli
                                      │
                                      ▼
                            ComplianceOrchestrator
                                      │
       ┌──────────────────────────────┼──────────────────────────────┐
       ▼                              ▼                              ▼
DeviceSelector                 ContextBuilder                ResourceRegistry
       │                              │                              │
       ▼ (REST API)                   ▼ (REST API)                   ▼ (Plugin Match)
NetBox SoT (Query Devices)    NetBox SoT (Desired State)     PortSecurityResource
       │                              │                              │
       └──────────────────────────────┼──────────────────────────────┘
                                      │
                                      ├──────────────────────────────┐
                                      ▼                              ▼
                        extract_desired_state()         get_collection_requests()
                                      │                 ('show port-security ...')
                                      │                              │
                                      │                              ▼
                                      │                       CollectorFactory
                                      │                              │
                                      │                              ▼
                                      │                        SSHCollector
                                      │                    (Read-Only SSH Show)
                                      │                              │
                                      │                              ▼
                                      │                     parse_actual_state()
                                      │                      (Actual State Map)
                                      │                              │
                                      └──────────────┬───────────────┘
                                                     ▼
                                              StateComparator
                                      (Recursive Tree Comparison)
                                                     ▼
                                             ComplianceReporter
                                      (CLI PASS / DRIFT ASCII Report)
```

---

## 4. Import Layer

### Complete Flow
```text
run_import.py (Root Wrapper)
     ↓
python/importers/run_import.py (main)
     ↓
1. run_dcim_import()           (Imports DCIM hierarchy & custom fields)
2. run_ipam_import()           (Imports VLANs, prefixes, IP addresses, SVI assignment)
3. run_config_context_import() (Imports Global-Defaults & Site-Defaults CSV contexts)
4. run_validation()            (Validates imported objects via NetBox REST API)
```

### Execution Details
- **Initiator Script**: `run_import.py` in repository root adds `python/importers/` to `sys.path` and executes `main()` in `python/importers/run_import.py`.
- **Core Module**: `python/importers/common_api.py` manages a persistent HTTP session (`requests.Session`) with header `Authorization: Bearer <NETBOX_TOKEN>`.
- **Functions & NetBox Endpoints**:
  1. `import_dcim.py` -> `run_dcim_import()`:
     - Calls `api_post("dcim/manufacturers/", ...)`
     - Calls `api_post("dcim/platforms/", ...)` (e.g. `cisco-ios`)
     - Calls `api_post("dcim/device-types/", ...)` (e.g. `ws-c3750x-24p`)
     - Calls `api_post("dcim/sites/", ...)`, `dcim/racks/`, `dcim/devices/`
     - Calls `api_post("extras/custom-fields/", ...)` to register custom field `port_security` on `dcim.interface`.
     - Calls `api_post("dcim/interfaces/", ...)` and populates `custom_fields["port_security"]`.
  2. `import_ipam.py` -> `run_ipam_import()`:
     - Calls `api_post("ipam/vlans/", ...)`
     - Calls `api_post("ipam/prefixes/", ...)` (e.g. `192.168.1.0/24`)
     - Calls `api_post("ipam/ip-addresses/", ...)` (e.g. `192.168.1.20/24`)
     - Assigns IP address object to interface `Vlan100`.
     - Sets `primary_ip4` on device `sw-access-01`.
  3. `import_config_context.py` -> `run_config_context_import()`:
     - Calls `api_post("extras/config-contexts/", ...)`
     - Creates `Global-Defaults` context (weight 1000).
     - Creates `Site-Defaults-hyderabad` context (weight 2000).
  4. `run_import.py` -> `run_validation()`:
     - Queries NetBox API to verify count > 0 for all created objects and prints summary status table.

---

## 5. Deployment Layer

### Complete Execution Architecture

```text
python -m deployment.cli
        ↓
deployment/cli.py (main)
        ↓
deployment/main.py (DeploymentOrchestrator.run)
        ↓
deployment/device_selector.py (DeviceSelector.select_devices)
        ↓
deployment/netbox_client.py (NetBoxClient.get_paginated)
        ↓
deployment/context_builder.py (ContextBuilder.build_device_context)
        ↓
deployment/credentials.py (CredentialResolver.resolve_connection_details)
        ↓
deployment/config_generator.py (ConfigGenerator.generate_configuration)
        ↓
deployment/protocols/port_security.py (PortSecurityProtocol.render)
        ↓
deployment/device_connector.py (DeviceConnector.deploy)
        ↓
Physical Network Switch (via Netmiko SSH)
```

### Architectural File Details

#### `deployment/cli.py`
- **Need**: Command-line entry point for administrators.
- **Why**: Allows dynamic runtime execution without modifying Python source code.
- **Input**: CLI arguments (`-d/--devices`, `-p/--protocols`, `-i/--interfaces`, `-s/--save-config`, `--dry-run`).
- **Output**: Returns status code `0` (success) or `1` (failures). Prints pre-flight summary and execution results.
- **Calls**: `DeploymentOrchestrator.run()`.
- **Called By**: Network Administrator / Automation Scripts.

#### `deployment/main.py`
- **Need**: Central pipeline orchestrator (`DeploymentOrchestrator`).
- **Why**: Enforces dependency order across deployment stages and supports dry-run execution mode.
- **Input**: `DeploymentRequest` dataclass instance.
- **Output**: `DeploymentSummary` dataclass containing device execution metrics.
- **Calls**: `DeviceSelector`, `ContextBuilder`, `CredentialResolver`, `ConfigGenerator`, `DeviceConnector`.
- **Called By**: `deployment/cli.py`.

#### `deployment/netbox_client.py`
- **Need**: Generic HTTP client wrapper (`NetBoxClient`) for NetBox REST API.
- **Why**: Handles pagination (`next` URL handling), error handling, and authentication.
- **Input**: Endpoint paths, query params, payload dicts.
- **Output**: Parsed JSON dictionaries/lists returned by NetBox API.
- **Calls**: `requests.Session` (`GET`, `POST`, `PATCH`).
- **Called By**: `DeviceSelector`, `ContextBuilder`.

#### `deployment/device_selector.py`
- **Need**: Target device filtering engine (`DeviceSelector`).
- **Why**: Allows selecting devices dynamically using NetBox criteria (`name`, `site`, `role`, `name__in`).
- **Input**: Criteria dictionary (e.g. `{"name": "sw-access-01"}` or `{"site": "hyderabad"}`).
- **Output**: List of NetBox device dictionaries.
- **Calls**: `NetBoxClient.get_paginated("dcim/devices/", criteria)`.
- **Called By**: `DeploymentOrchestrator`.

#### `deployment/context_builder.py`
- **Need**: Unified device context builder (`ContextBuilder`).
- **Why**: Implements the 3-level context merge rule: `Global-Defaults` → `Site-Defaults-<site>` → `device.local_context_data`.
- **Input**: Single NetBox device dictionary.
- **Output**: Comprehensive device context dictionary containing merged config, identity, platform, role, management IP, interfaces, VLANs, and custom fields.
- **Calls**: `NetBoxClient` (`extras/config-contexts/`, `dcim/interfaces/`, `ipam/ip-addresses/`).
- **Called By**: `DeploymentOrchestrator`.

#### `deployment/credentials.py`
- **Need**: Secret resolution layer (`CredentialResolver`).
- **Why**: Keeps secrets (passwords, secrets) out of NetBox. Maps NetBox device role (`access`, `core`) to environment SSH profiles in `.env`.
- **Input**: NetBox device dictionary.
- **Output**: Connection details dictionary (`host`, `username`, `password`, `secret`, `device_type`, `port`, `timeout`).
- **Calls**: `deployment.config.get_profile_credentials()`.
- **Called By**: `DeploymentOrchestrator`.

#### `deployment/config_generator.py`
- **Need**: Configuration renderer engine (`ConfigGenerator`).
- **Why**: Auto-discovers protocol plugins and coordinates rendering for selected protocols/interfaces.
- **Input**: Unified device context map, protocol list, interface list.
- **Output**: Formatted Cisco CLI configuration string.
- **Calls**: Protocol plugins inheriting from `BaseProtocol`.
- **Called By**: `DeploymentOrchestrator`.

#### `deployment/device_connector.py`
- **Need**: SSH configuration deployment transport (`DeviceConnector`).
- **Why**: Establishes Netmiko SSH sessions, enters configuration mode, pushes CLI commands, and optionally saves config.
- **Input**: Switch connection details dict, CLI configuration string, `save_config` boolean flag.
- **Output**: `DeploymentResult` dataclass (commands sent, execution time, status, error messages).
- **Calls**: `netmiko.ConnectHandler` (`send_config_set()`, `save_config()`).
- **Called By**: `DeploymentOrchestrator`.

---

## 6. Protocol Plugin Architecture

### Inheritance Hierarchy
```text
             BaseProtocol (deployment/protocols/base_protocol.py)
                   │
                   ▼
       PortSecurityProtocol (deployment/protocols/port_security.py)
```

### Key Plugin Contracts (`BaseProtocol`)
Every deployment protocol plugin inherits from `BaseProtocol` and implements:
1. `protocol_name`: Unique string identifier (e.g. `"port_security"`).
2. `is_applicable(device_context) -> bool`: Determines if plugin configuration exists in context.
3. `validate(device_context) -> None`: Validates context parameters before CLI rendering.
4. `render(device_context) -> str`: Renders Cisco CLI commands from context.

### Dynamic Discovery (`ConfigGenerator`)
`ConfigGenerator` uses Python's `pkgutil.iter_modules` to scan the `deployment/protocols/` package at startup. Any class inheriting from `BaseProtocol` is automatically instantiated and registered in an internal dictionary:
```python
self._plugins = { "port_security": PortSecurityProtocol(), ... }
```

### Adding New Protocol Plugins
To add a new protocol (e.g., `ospf.py` or `vlan.py`):
1. Create `deployment/protocols/ospf.py`.
2. Subclass `BaseProtocol`.
3. Implement `protocol_name`, `is_applicable`, `validate`, and `render`.
4. **No changes are required in `ConfigGenerator` or `cli.py`**.

---

## 7. Compliance Layer

### Complete Execution Architecture

```text
python -m compliance.cli
        ↓
compliance/cli.py (main)
        ↓
compliance/main.py (ComplianceOrchestrator.run)
        ↓
deployment/device_selector.py (DeviceSelector.select_devices) [REUSED]
        ↓
deployment/context_builder.py (ContextBuilder.build_device_context) [REUSED]
        ↓
deployment/credentials.py (CredentialResolver.resolve_connection_details) [REUSED]
        ↓
compliance/resources/registry.py (ResourceRegistry.get_applicable_resources)
        ↓
compliance/resources/port_security.py (PortSecurityResource)
        ├─► extract_desired_state()  -> Desired State Map
        └─► get_collection_requests() -> ['show port-security interface ...']
        ↓
compliance/collectors/factory.py (CollectorFactory.get_collector)
        ↓
compliance/collectors/ssh_collector.py (SSHCollector.collect)
        ↓ (Read-Only SSH over Netmiko)
compliance/resources/port_security.py (parse_actual_state) -> Actual State Map
        ↓
compliance/comparator.py (StateComparator.compare) -> Field Comparisons
        ↓
compliance/report.py (ComplianceReporter.print_execution_results) -> ASCII Report
```

### Architectural File Details

#### `compliance/cli.py`
- **Need**: Command-line entry point for compliance checks.
- **Why**: Allows dynamic compliance checks (`--devices`, `--protocols`, `--interfaces`).
- **Input**: CLI arguments.
- **Output**: Returns status code `0` (COMPLIANT) or `1` (DRIFT/FAILED).
- **Calls**: `ComplianceOrchestrator.run()`.

#### `compliance/main.py`
- **Need**: Central compliance engine (`ComplianceOrchestrator`).
- **Why**: Coordinates selection, context retrieval, read-only SSH collection, parsing, comparison, and reporting. Contains ZERO protocol-specific hardcoding.
- **Input**: `ComplianceRequest` dataclass.
- **Output**: `ComplianceSummary` dataclass.
- **Calls**: `DeviceSelector`, `ContextBuilder`, `CredentialResolver`, `ResourceRegistry`, `CollectorFactory`, `StateComparator`, `ComplianceReporter`.

#### `compliance/comparator.py`
- **Need**: Protocol-agnostic recursive state comparator (`StateComparator`).
- **Why**: Compares expected primitive dictionary values against actual primitive values without knowing protocol specifics.
- **Input**: `desired_state` dict, `actual_state` dict.
- **Output**: List of `FieldComparison` objects (`field_path`, `expected_value`, `actual_value`, `status: PASS/DRIFT`).
- **Calls**: Internal recursive dictionary traversal.

#### `compliance/report.py`
- **Need**: Structured reporting & CLI formatter (`ComplianceReporter`).
- **Why**: Formats evaluation results into human-readable ASCII tables and device status summaries.
- **Input**: `ComplianceSummary` dataclass instance.
- **Output**: Console output reports.

---

## 8. Resource Plugin Architecture

### Inheritance Hierarchy
```text
             BaseResource (compliance/resources/base_resource.py)
                  │
                  ▼
       PortSecurityResource (compliance/resources/port_security.py)
```

### Key Plugin Contracts (`BaseResource`)
Every compliance resource plugin inherits from `BaseResource` and implements:
1. `resource_name`: Unique string identifier (e.g. `"port_security"`).
2. `supports_device(device_context) -> bool`: Checks if plugin supports the vendor/platform capability.
3. `is_configured(device_context) -> bool`: Checks if desired state for this resource exists in NetBox context.
4. `extract_desired_state(device_context, interfaces) -> dict`: Extracts normalized desired state from NetBox context.
5. `get_collection_requests(device_context, desired_state) -> list[str]`: Returns required read-only `show` commands.
6. `parse_actual_state(raw_outputs, device_context, desired_state) -> dict`: Parses raw CLI text into normalized actual state map.

### Dynamic Discovery (`ResourceRegistry`)
`ResourceRegistry` in `compliance/resources/registry.py` scans `compliance/resources/` using `pkgutil.iter_modules` at runtime.

When `get_applicable_resources(device_context)` is called, it checks:
```python
if plugin.supports_device(device_context) and plugin.is_configured(device_context):
    applicable.append(plugin)
```

### Adding Future Resource Plugins (OSPF, BGP, VLAN, STP, WLAN, AP)
To add a new compliance resource (e.g., `ospf.py` or `wlan.py`):
1. Create `compliance/resources/ospf.py`.
2. Subclass `BaseResource`.
3. Implement `supports_device`, `is_configured`, `extract_desired_state`, `get_collection_requests`, and `parse_actual_state`.
4. **No changes are required in `ComplianceOrchestrator`, `StateComparator`, or `cli.py`**.

---

## 9. Collector Architecture

### Inheritance Hierarchy
```text
             BaseCollector (compliance/collectors/base_collector.py)
                   │
                   ▼
         SSHCollector (compliance/collectors/ssh_collector.py)
```

### Transport Abstraction
- `BaseCollector`: Abstract contract defining `collect(device_name, connection_details, commands) -> dict[str, str]`.
- `SSHCollector`: Implements Netmiko SSH execution.
  - **READ-ONLY SAFETY GUARANTEE**: Only invokes `ConnectHandler.send_command()`. Never invokes `send_config_set()` or `save_config()`. Handles invalid CLI responses (`% Invalid input`) by returning `N/A (Interface Invalid/Missing on Switch)`.
- `CollectorFactory`: Selects collector based on connection transport metadata (`ssh`, `netconf`, `rest`).

### Future Collector Extensions
- **`RESTCollector`**: For Cisco Catalyst Center, Meraki, WLC REST APIs.
- **`NetconfCollector`**: For NETCONF RPC XML retrieval (`ncclient`).

---

## 10. Current Data Flow Example

### Target Context
- **Device**: `sw-access-01`
- **Interface**: `GigabitEthernet3/0/5`
- **Protocol**: `port_security`

### End-to-End Execution Trace

```text
1. NetBox (Desired State)
   - Interface GigabitEthernet3/0/5 custom fields:
     {
       "enabled": true,
       "max_mac_addresses": 2,
       "violation": "restrict",
       "aging_time": 10,
       "aging_type": "inactivity"
     }

2. Deployment Layer Execution
   - python -m deployment.cli --devices sw-access-01 --protocols port_security --interfaces GigabitEthernet3/0/5
   - ContextBuilder merges device context.
   - PortSecurityProtocol renders Cisco CLI:
     interface GigabitEthernet3/0/5
      switchport port-security
      switchport port-security maximum 2
      switchport port-security violation restrict
      switchport port-security aging time 10
      switchport port-security aging type inactivity
   - DeviceConnector connects over SSH and applies commands to switch.

3. Compliance Layer Execution
   - python -m compliance.cli --devices sw-access-01 --protocols port_security --interfaces GigabitEthernet3/0/5
   - Desired State Map extracted from NetBox:
     {"interfaces": {"GigabitEthernet3/0/5": {"enabled": True, "max_mac_addresses": 2, "violation": "restrict", "aging_time": 10, "aging_type": "inactivity"}}}
   - SSHCollector runs read-only command:
     `show port-security interface GigabitEthernet3/0/5`
   - Actual State Map parsed from switch response:
     {"interfaces": {"GigabitEthernet3/0/5": {"enabled": True, "max_mac_addresses": 2, "violation": "restrict", "aging_time": 10, "aging_type": "inactivity"}}}
   - StateComparator compares maps:
     enabled: True == True -> PASS
     max_mac_addresses: 2 == 2 -> PASS
     violation: restrict == restrict -> PASS
     aging_time: 10 == 10 -> PASS
     aging_type: inactivity == inactivity -> PASS
   - ComplianceReporter outputs: Overall Status: COMPLIANT (PASS)
```

---

## 11. Current Features Implemented

- [x] **NetBox Importer**: Automated ingestion of DCIM, IPAM, and Config Context CSV files into NetBox.
- [x] **3-Tier Context Builder**: Deep dictionary merge (`Global-Defaults` → `Site-Defaults` → `Device Local Context`).
- [x] **Environment Credential Resolution**: Secret isolation using `.env` profiles mapped to device roles.
- [x] **Generic Deployment CLI**: Dynamic targeting (`--devices`, `--protocols`, `--interfaces`).
- [x] **Safety Dry-Run Mode**: Audit simulation mode (`--dry-run`) generating CLI without SSH connections.
- [x] **Plugin-Based Generator**: Auto-discovery of deployment protocol plugins (`BaseProtocol`).
- [x] **Port Security Deployment**: End-to-end rendering and push of Port Security settings.
- [x] **Generic Compliance CLI**: Dynamic read-only compliance evaluation (`python -m compliance.cli`).
- [x] **Read-Only SSH Transport**: Non-intrusive `SSHCollector` executing only `show` commands.
- [x] **Dynamic Resource Registry**: Auto-discovery of compliance resource plugins (`BaseResource`).
- [x] **Protocol-Agnostic Comparator**: Recursive tree comparator evaluating desired vs actual primitive states.
- [x] **CLI Report Generator**: ASCII table output displaying field-level expected vs actual values and `PASS`/`DRIFT` status.

---

## 12. Future Features

- [ ] **Deployment Protocol Plugins**: `OSPF`, `BGP`, `VLAN`, `STP`, `NTP`, `DHCP Snooping`.
- [ ] **Compliance Resource Plugins**: `OSPFResource`, `BGPResource`, `VLANResource`, `STPResource`, `WLANResource`.
- [ ] **Transport Collectors**: `RESTCollector` (WLC / AP APIs), `NetconfCollector`.
- [ ] **Automated Remediation Workflow**: Admin-approved drift remediation triggered from compliance findings.
- [ ] **Web Compliance Dashboard**: Graphical UI summary of enterprise network drift.

---

## 13. Important Files Table

| File | Purpose | Who Uses It | Depends On | Returns |
| --- | --- | --- | --- | --- |
| `deployment/cli.py` | CLI entry point for deployment pipeline. | Admin / Automation | `DeploymentOrchestrator` | Exit code `0` or `1` |
| `deployment/main.py` | Pipeline orchestrator. | `cli.py` | Selector, ContextBuilder, CredentialResolver, Generator, Connector | `DeploymentSummary` |
| `deployment/netbox_client.py` | REST API client for NetBox. | `DeviceSelector`, `ContextBuilder` | NetBox REST endpoints | Parsed JSON dicts/lists |
| `deployment/device_selector.py` | Filters devices from NetBox. | `DeploymentOrchestrator` | `NetBoxClient` | List of device dicts |
| `deployment/context_builder.py` | Merges 3-level configuration context. | `DeploymentOrchestrator` | `NetBoxClient` | Unified device context map |
| `deployment/credentials.py` | Resolves management IP & SSH secrets. | `DeploymentOrchestrator` | `deployment.config` (.env) | Connection details dict |
| `deployment/config_generator.py` | Renders Cisco CLI commands. | `DeploymentOrchestrator` | `BaseProtocol` plugins | Formatted CLI text |
| `deployment/device_connector.py` | SSH deployment transport over Netmiko. | `DeploymentOrchestrator` | `netmiko.ConnectHandler` | `DeploymentResult` |
| `compliance/cli.py` | CLI entry point for compliance evaluation. | Admin / Automation | `ComplianceOrchestrator` | Exit code `0` or `1` |
| `compliance/main.py` | Compliance workflow orchestrator. | `compliance/cli.py` | Selector, ContextBuilder, Registry, Collector, Comparator, Reporter | `ComplianceSummary` |
| `compliance/resources/registry.py` | Auto-discovers compliance plugins. | `ComplianceOrchestrator` | `BaseResource` plugins | List of active plugins |
| `compliance/collectors/ssh_collector.py` | Executes read-only `show` commands. | `ComplianceOrchestrator` | Netmiko | Raw CLI output dict |
| `compliance/comparator.py` | Compares desired vs actual state maps. | `ComplianceOrchestrator` | Standard primitives | List of `FieldComparison` |
| `compliance/report.py` | Formats ASCII CLI reports. | `ComplianceOrchestrator` | Outcome dataclasses | Console text report |

---

## 14. Complete Execution Sequence

### Deployment Sequence
```text
User            CLI            Orchestrator       NetBox         Generator       Connector       Switch
 │               │                  │               │                │               │              │
 │─python -m deployment.cli───────>│               │                │               │              │
 │               │                  │─select───────>│                │               │              │
 │               │                  │<──devices─────│                │               │              │
 │               │                  │─build_context>│                │               │              │
 │               │                  │<──context─────│                │               │              │
 │               │                  │─resolve_creds─────────────────────────────────────────────────> (.env)
 │               │                  │─generate_config───────────────>│               │              │
 │               │                  │<──cli_string───────────────────│               │              │
 │               │                  │─deploy_config─────────────────────────────────>│              │
 │               │                  │                                                │─SSH Push────>│
 │               │                  │                                                │<──Success────│
 │               │<──Summary────────│                                                │              │
 │<──Report──────│                  │                                                │              │
```

### Compliance Sequence
```text
User            CLI            Orchestrator       NetBox          Registry       Collector      Comparator
 │               │                  │               │                │               │              │
 │─python -m compliance.cli────────>│               │                │               │              │
 │               │                  │─select───────>│                │               │              │
 │               │                  │<──devices─────│                │               │              │
 │               │                  │─build_context>│                │               │              │
 │               │                  │<──context─────│                │               │              │
 │               │                  │─get_plugins───────────────────>│               │              │
 │               │                  │<──plugins──────────────────────│               │              │
 │               │                  │─collect_show_commands─────────────────────────>│              │
 │               │                  │                                                │─SSH Show────> Switch
 │               │                  │                                                │<──Raw Output── Switch
 │               │                  │─compare(desired, actual)─────────────────────────────────────>│
 │               │                  │<──field_results───────────────────────────────────────────────│
 │               │<──Summary────────│                                                               │
 │<──Report──────│                  │                                                               │
```

---

## 15. Lessons Learned / Design Decisions

1. **Why Plugin Architecture?**: Hardcoding protocol logic (`if protocol == "port_security"`) makes code unmaintainable at scale. Plugin inheritance (`BaseProtocol`, `BaseResource`) allows adding new network protocols by simply adding a file without editing central core engines.
2. **Why 3-Tier ContextBuilder?**: Network configurations follow visual inheritance (Global Defaults → Site Specifics → Device Overrides). Merging contexts in NetBox order enforces consistency across 1000+ devices.
3. **Why CredentialResolver via `.env`?**: NetBox stores network intent, not passwords. Decoupling connection secrets into environment profiles protects security credentials from source control exposure.
4. **Why Compliance Is Strictly Read-Only**: Compliance checks must never alter network state or crash production switches. Enforcing `send_command()` read-only execution guarantees zero-risk auditability.
5. **Why Deployment and Compliance Are Separate**: Conflating deployment with compliance leads to unintended automatic changes. Separating them establishes an explicit audit phase where administrators review drift before deciding to deploy.

---

## 16. Glossary

- **ContextBuilder**: Module that aggregates Global, Site, and Device Local contexts from NetBox into a unified configuration dictionary.
- **Desired State**: The intended network policy defined in NetBox (Source of Truth).
- **Actual State**: The live operational state retrieved directly from the network switch via read-only commands.
- **Resource Plugin**: Self-contained compliance module (`BaseResource`) that extracts desired state, requests show commands, and parses actual CLI output for a specific protocol.
- **Protocol Plugin**: Self-contained deployment module (`BaseProtocol`) that validates context and renders Cisco CLI configuration.
- **Collector**: Transport module (`BaseCollector`) responsible for establishing device connections and returning raw operational data.
- **Comparator**: Engine (`StateComparator`) that recursively compares expected vs actual primitive state dictionaries.
- **Deployment**: Workflow that generates and applies CLI configuration changes to network devices.
- **Compliance**: Read-only workflow that detects differences (drift) between NetBox and network devices.

---

## 17. Final Project Synopsis

### Executive Summary
The **`enterprise_real_sot`** repository implements an Enterprise **Network-as-Code (NAC)** automation framework centered on **NetBox** as the single runtime Source of Truth. It replaces manual switch configuration with two independent, fully decoupled automation pipelines:

1. **Deployment Layer (`deployment/`)**: Reads network intent from NetBox, dynamically resolves switch management IPs and local `.env` SSH credentials, renders deterministic Cisco CLI configuration via protocol plugins, and pushes changes to devices using Netmiko SSH. Supports `--dry-run` safety audits.
2. **Compliance Layer (`compliance/`)**: Performs read-only audit checks. Queries NetBox desired state, executes non-intrusive `show` commands over SSH, parses live operational data into normalized state maps, and performs generic recursive dictionary comparison to report `PASS` or `DRIFT` status without modifying switches or NetBox.

### Architecture At A Glance
- **NetBox API Client (`NetBoxClient`)**: Generic REST client handling pagination and authentication.
- **Device Selection (`DeviceSelector`)**: Dynamic filter querying NetBox by name, site, or role.
- **Context Merging (`ContextBuilder`)**: Hierarchical 3-tier merge (`Global-Defaults` → `Site-Defaults` → `Device Local Context`).
- **Secret Isolation (`CredentialResolver`)**: Dynamic environment mapping (`.env` SSH profiles).
- **Dynamic Extensibility**: Plugin auto-discovery (`ResourceRegistry` and `ConfigGenerator`) allowing engineers to add new protocols (OSPF, BGP, VLANs, WLANs) by simply adding a Python plugin file without modifying central core engines.

### Key Commands
```bash
# 1. Run NetBox Importer (Populate NetBox from CSVs)
python run_import.py

# 2. Deployment Pipeline (Dry-Run Audit Mode)
python -m deployment.cli --devices sw-access-01 --protocols port_security --interfaces GigabitEthernet3/0/5 --dry-run

# 3. Deployment Pipeline (Live Execution Mode)
python -m deployment.cli --devices sw-access-01 --protocols port_security --interfaces GigabitEthernet3/0/5 --save-config

# 4. Compliance Layer (Read-Only Drift Evaluation)
python -m compliance.cli --devices sw-access-01 --protocols port_security --interfaces GigabitEthernet3/0/5
python -m compliance.cli --devices sw-access-01 --protocols port_security --interfaces all
```
