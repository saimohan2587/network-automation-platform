# Enterprise Network Automation Controller (NAC)

## Purpose

Enterprise Network Automation Controller (NAC) manages enterprise network operational state through NetBox. Its business goal is to make network intent consistent, queryable, and automatable as the estate grows from the current 10 Cisco devices to 10,000+ devices and from approximately 15 protocols to 100+ protocols.

NetBox is the runtime source of truth. All deployment decisions and device configuration inputs must be derived from NetBox at execution time.

## Current State: Import Layer Complete

The completed Import Layer establishes NetBox data from the repository's CSV source data:

```text
csv/ → python/importers/ → NetBox
```

`python/importers/run_import.py` is the project entry point for the Import Layer. It executes the following ordered stages:

1. DCIM import: manufacturers, roles, platforms, device types, regions, site groups, sites, locations, racks, devices, and interfaces.
2. IPAM import: VLANs, prefixes, IP addresses, interface assignments, and primary IPv4 assignments.
3. Configuration-context import: global defaults, site defaults, and device-local context data.
4. Validation and import summary reporting.

The importer is idempotent for its managed objects: it resolves existing NetBox records before creating them and updates devices, interfaces, and named configuration contexts where appropriate. This layer is complete and is not to be redesigned or modified as part of Deployment Layer work.

## Repository Technology

- Python is the implementation language.
- CSV files under `csv/` are the Import Layer input.
- NetBox REST API is used for DCIM, IPAM, and Extras data.
- `requests` provides HTTP sessions; the Deployment Layer client adds retry, pagination, and connection reuse.
- Configuration context values are represented as CSV `key,value` pairs, with JSON decoded when applicable.
- The current estate models Cisco IOS devices (`cisco-ios`), including access, distribution, and core switch roles at the Hyderabad site.

## Existing Deployment Foundations

The `deployment/` package already contains reusable runtime-read components:

- `NetBoxClient` manages authenticated REST access, retries, and pagination.
- `DeviceSelector` translates dynamic request criteria into NetBox device queries.
- `ContextBuilder` creates a device context from NetBox global/site config contexts, device local context, interfaces, and IP addresses.
- `utils.deep_merge` implements the runtime dictionary-merge behaviour.
- `logger` supplies consistent deployment logging.

These components are foundations, not a completed device deployment pipeline. Configuration generation, protocol plugins, device connection, and Cisco execution remain future work.

## Target State

```text
NetBox → Deployment Layer → Cisco Devices
```

The Deployment Layer must select devices from NetBox, assemble their effective context, generate protocol-specific configuration, and apply it through a device connector. It must never read `csv/` files. CSV remains an Import Layer concern only.

## Architectural Objective

The architecture must scale by adding small, independent modules instead of growing a single workflow. New protocols, device platforms, selection methods, or transport implementations must integrate through explicit interfaces while preserving NetBox as the runtime authority.
