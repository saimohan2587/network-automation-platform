# NetBox Data Model

## Runtime Source of Truth

NetBox is NAC's runtime source of truth. The Deployment Layer queries NetBox at execution time for device identity, selection attributes, addressing, interfaces, and effective configuration intent. CSV files are only the completed Import Layer's source data and are never a deployment input.

## DCIM

### Devices

Devices are the primary deployment targets in `dcim/devices/`. Current records include Cisco IOS access, distribution, and core switches such as the `sw-access-*`, `sw-dist-*`, and `sw-core-*` estate. A device carries its name, status, role, device type, platform, site, optional location/rack placement, primary IP, and `local_context_data`.

`local_context_data` stores device-specific operational configuration imported from `csv/config_context/devices/<site>/<role>/<device>.csv`. Examples in the current data include VLAN definitions, DHCP snooping, IPv6 behaviour, EtherChannel, OSPF, HSRP, DHCP relay, static routes, and interface-specific settings.

### Interfaces

Interfaces in `dcim/interfaces/` belong to a device and represent the deployable port model. The Import Layer records interface name, type, administrative state, management-only flag, description, switching mode, untagged VLAN, tagged VLANs, and LAG membership.

Interface custom fields currently include the JSON `port_security` field. Runtime context construction also associates IP addresses with each interface.

### Roles

Device roles classify a device's operational function and are stored in `dcim/device-roles/`. The current inventory uses access, distribution, and core role patterns. Roles are selection and policy inputs; deployment logic must query them rather than branch on device names.

### Sites

Sites in `dcim/sites/` anchor geography and configuration scope. The current model contains Hyderabad, within the India region and Telangana site group, with the Addagutta Society location and JNTU-LAB-RACK-01 rack. Site slugs are used to locate the corresponding site configuration context named `Site-Defaults-<site slug>`.

### Platforms

Platforms in `dcim/platforms/` describe the network operating system. The current platform is Cisco IOS with slug `cisco-ios`, associated with Cisco as manufacturer. Platform is a key input for future generator and connector selection.

### Device Types and Physical Placement

Device types map a manufacturer to a model; locations and racks provide physical placement. These objects are imported before devices to maintain valid relationships. They may support future policy and hardware-capability decisions but are not substitutes for a device's platform or role.

## IPAM

### VLANs

VLANs in `ipam/vlans/` define the current enterprise segments: Finance (10), Engineering (20), Guest (30), Voice (40), Printers (50), Servers (60), and Management (100). Interfaces reference VLAN objects for access and tagged operation.

### Prefixes and IP Addresses

Prefixes in `ipam/prefixes/` define routed address space. IP addresses in `ipam/ip-addresses/` are assigned to interfaces; selected addresses are marked as a device's primary IPv4. The runtime context includes assigned interface addresses and exposes the primary IP in `device_info`.

## Extras

### Config Context

Configuration contexts express hierarchical configuration intent:

| Scope | NetBox object | Current source |
| --- | --- | --- |
| Global | `Global-Defaults` | `csv/config_context/global/global_defaults.csv` |
| Site | `Site-Defaults-hyderabad` | `csv/config_context/sites/hyderabad.csv` |
| Device | `local_context_data` on the device | `csv/config_context/devices/hyderabad/...` |

The runtime precedence is global, then site, then device. Nested dictionaries are merged; a more-specific value overrides the less-specific value. The current global baseline includes DNS, NTP, AAA, syslog, SNMP, STP, VTP, LLDP, and CDP settings.

### Custom Fields

Custom fields extend NetBox data where standard fields are insufficient. The completed importer ensures the `port_security` JSON custom field exists on `dcim.interface`. Future custom fields must have a documented ownership and clear runtime consumer before being introduced.

### Tags

Tags are supported by `DeviceSelector` as a NetBox-based dynamic selection criterion. They should classify devices for operational targeting such as rollout rings, service ownership, or deployment cohorts. Tags must be maintained in NetBox and never duplicated as hardcoded lists in deployment code.

## Data Ownership Rules

- Import Layer owns CSV-to-NetBox synchronization.
- NetBox owns the runtime representation used by deployment.
- Deployment Layer reads NetBox; it does not rewrite Import Layer source data.
- A schema or naming change to NetBox data must preserve the Context Builder contract or include an explicit, tested update to its consumers.
