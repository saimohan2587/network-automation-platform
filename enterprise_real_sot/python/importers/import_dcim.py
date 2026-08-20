"""
Purpose   : Imports physical hardware inventory (manufacturers, sites, racks, devices, interfaces) from CSV into NetBox DCIM.
Called By : run_import.py (`run_dcim_import()`).
Calls Next: NetBox REST API (`/api/dcim/`) via common_api.py.
"""

############################################################
# WHY DOES THIS MODULE EXIST?
#
# DCIM stands for Data Center Infrastructure Management. It represents physical and
# topological network inventory: Manufacturers, Sites, Racks, Device Types, Devices,
# Interfaces, VLAN assignments, and Port Security settings.
#
# This module (`import_dcim.py`) reads CSV files from `csv/dcim/` and populates NetBox
# in strict dependency order (e.g., Sites and Manufacturers must exist before Devices can be created).
#
# REAL-WORLD ANALOGY:
# Imagine setting up a company inventory catalog. Before adding a specific laptop
# ("Switch-01"), you must first define the brand ("Cisco"), the office building ("Hyderabad Site"),
# and the equipment rack ("Rack-A1"). This script sets up the entire catalog hierarchy.
############################################################

import os
import csv
import logging
import sys
from common_api import (
    api_post, api_patch, resolve_by_slug, resolve_manufacturer, resolve_device_role,
    resolve_platform, resolve_device_type, resolve_region, resolve_site_group,
    resolve_site, resolve_location, resolve_rack, resolve_device, api_get, stats
)

# Ensure the parser module is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..', 'src')))
# pyrefly: ignore [missing-import]
from parser import YamlLoader


logger = logging.getLogger("NetBoxImporter")

############################################################
# CSV FILE LOCATION AND READING UTILITIES
#
# 1. Why this code exists:
#    `get_csv_path()` searches multiple relative directory paths to find a CSV file.
#    `read_csv()` opens the file and converts CSV rows into Python dictionaries.
#
# 2. What problem it solves:
#    Handles path differences depending on whether the script is run from project root,
#    the `python/importers/` directory, or inside a Docker container.
#
# 3. Which module will use it next:
#    Used by every importer function in this file (`import_manufacturers`, `import_devices`, etc.).
#
# 4. What happens if this code is removed:
#    The script won't find or read CSV files, halting the import process.
#
# 5. Real-world analogy:
#    Like a mail clerk checking multiple incoming trays to find a requested paper file folder.
############################################################
def get_csv_path(filename):
    # Try looking in multiple locations relative to current script
    paths_to_try = [
        os.path.join(os.path.dirname(__file__), '../../csv/dcim', filename),
        os.path.join(os.getcwd(), 'csv/dcim', filename),
        os.path.join(os.getcwd(), 'enterprise_real_sot/csv/dcim', filename)
    ]
    for p in paths_to_try:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"Could not find CSV file: {filename}")

def read_csv(path):
    if not os.path.exists(path):
        logger.error(f"CSV file not found: {path}")
        return []
    with open(path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return [row for row in reader]

############################################################
# PREREQUISITE INFRASTRUCTURE IMPORTERS
# (Manufacturers, Roles, Platforms, Device Types, Regions, Sites, Racks)
#
# 1. Why this code exists:
#    NetBox requires foundational reference metadata to exist before actual physical
#    switches can be added. These functions read their respective CSV files, check if
#    the object already exists in NetBox (to avoid duplicates), and create missing items.
#
# 2. What problem it solves:
#    Guarantees idempotency (running the script twice won't create duplicate manufacturers or sites).
#
# 3. Which module will use it next:
#    `import_devices()` resolves these objects by name/slug to retrieve their database IDs.
#
# 4. What happens if this code is removed:
#    Device imports will fail because required foreign keys (like site_id or manufacturer_id) will be missing.
#
# 5. Real-world analogy:
#    Building the shelves, labels, and room layout in a warehouse before stocking actual products.
############################################################
def import_manufacturers():
    path = get_csv_path('manufacturers.csv')
    rows = read_csv(path)
    for row in rows:
        slug = row['slug']
        existing = resolve_manufacturer(slug)
        if existing:
            logger.info(f"Manufacturer '{row['name']}' already exists. Skipping.")
            stats["skipped"] += 1
            continue
        data = {
            "name": row['name'],
            "slug": slug
        }
        api_post("dcim/manufacturers/", data)

def import_device_roles():
    path = get_csv_path('device_roles.csv')
    rows = read_csv(path)
    for row in rows:
        slug = row['slug']
        existing = resolve_device_role(slug)
        if existing:
            logger.info(f"Device Role '{row['name']}' already exists. Skipping.")
            stats["skipped"] += 1
            continue
        data = {
            "name": row['name'],
            "slug": slug,
            "color": row.get('color', '808080'),
            "vm_role": row.get('vm_role', 'false').lower() == 'true'
        }
        api_post("dcim/device-roles/", data)

def import_platforms():
    path = get_csv_path('platforms.csv')
    rows = read_csv(path)
    for row in rows:
        slug = row['slug']
        existing = resolve_platform(slug)
        if existing:
            logger.info(f"Platform '{row['name']}' already exists. Skipping.")
            stats["skipped"] += 1
            continue
        mfg_id = resolve_manufacturer(row['manufacturer'])
        if not mfg_id:
            logger.error(f"Cannot import platform '{row['name']}': Manufacturer '{row['manufacturer']}' not found.")
            stats["failed"] += 1
            continue
        data = {
            "name": row['name'],
            "slug": slug,
            "manufacturer": mfg_id
        }
        api_post("dcim/platforms/", data)

def import_device_types():
    path = get_csv_path('device_types.csv')
    rows = read_csv(path)
    for row in rows:
        slug = row['slug']
        existing = resolve_device_type(slug)
        if existing:
            logger.info(f"Device Type '{row['model']}' already exists. Skipping.")
            stats["skipped"] += 1
            continue
        mfg_id = resolve_manufacturer(row['manufacturer'])
        if not mfg_id:
            logger.error(f"Cannot import device type '{row['model']}': Manufacturer '{row['manufacturer']}' not found.")
            stats["failed"] += 1
            continue
        data = {
            "manufacturer": mfg_id,
            "model": row['model'],
            "slug": slug,
            "u_height": int(row.get('u_height', 1)),
            "is_full_depth": row.get('is_full_depth', 'true').lower() == 'true'
        }
        api_post("dcim/device-types/", data)

def import_regions():
    path = get_csv_path('regions.csv')
    rows = read_csv(path)
    for row in rows:
        slug = row['slug']
        existing = resolve_region(slug)
        if existing:
            logger.info(f"Region '{row['name']}' already exists. Skipping.")
            stats["skipped"] += 1
            continue
        data = {
            "name": row['name'],
            "slug": slug
        }
        api_post("dcim/regions/", data)

def import_site_groups():
    path = get_csv_path('site_groups.csv')
    rows = read_csv(path)
    for row in rows:
        slug = row['slug']
        existing = resolve_site_group(slug)
        if existing:
            logger.info(f"Site Group '{row['name']}' already exists. Skipping.")
            stats["skipped"] += 1
            continue
        data = {
            "name": row['name'],
            "slug": slug
        }
        api_post("dcim/site-groups/", data)

def import_sites():
    path = get_csv_path('sites.csv')
    rows = read_csv(path)
    for row in rows:
        slug = row['slug']
        existing = resolve_site(slug)
        if existing:
            logger.info(f"Site '{row['name']}' already exists. Skipping.")
            stats["skipped"] += 1
            continue
        region_id = resolve_region(row.get('region'))
        group_id = resolve_site_group(row.get('group'))
        data = {
            "name": row['name'],
            "slug": slug,
            "status": row.get('status', 'active').lower()
        }
        if region_id:
            data["region"] = region_id
        if group_id:
            data["group"] = group_id
        api_post("dcim/sites/", data)

def import_locations():
    path = get_csv_path('locations.csv')
    rows = read_csv(path)
    for row in rows:
        slug = row['slug']
        existing = resolve_location(slug)
        if existing:
            logger.info(f"Location '{row['name']}' already exists. Skipping.")
            stats["skipped"] += 1
            continue
        site_id = resolve_site(row['site'])
        if not site_id:
            logger.error(f"Cannot import location '{row['name']}': Site '{row['site']}' not found.")
            stats["failed"] += 1
            continue
        data = {
            "name": row['name'],
            "slug": slug,
            "site": site_id
        }
        api_post("dcim/locations/", data)

def import_racks():
    path = get_csv_path('racks.csv')
    rows = read_csv(path)
    for row in rows:
        site_id = resolve_site(row['site'])
        if not site_id:
            logger.error(f"Cannot import rack '{row['name']}': Site '{row['site']}' not found.")
            stats["failed"] += 1
            continue
        existing = resolve_rack(row['name'], site_id)
        if existing:
            logger.info(f"Rack '{row['name']}' already exists in Site ID {site_id}. Skipping.")
            stats["skipped"] += 1
            continue
        loc_id = resolve_location(row.get('location'))
        data = {
            "name": row['name'],
            "site": site_id,
            "u_height": int(row.get('u_height', 42)),
            "status": row.get('status', 'active').lower()
        }
        if loc_id:
            data["location"] = loc_id
        if row.get('facility_id'):
            data["facility_id"] = row['facility_id']
        api_post("dcim/racks/", data)

############################################################
# CONFIG CONTEXT HELPERS & CUSTOM FIELD INITIALIZER
#
# 1. Why this code exists:
#    `get_git_intent_data()` parses JSON values from `csv/config_context/devices/`.
#    `ensure_custom_fields()` creates NetBox custom fields (like `port_security` on interfaces).
#
# 2. What problem it solves:
#    Allows enterprise-specific data (like Port Security policies or custom VLAN rules)
#    to be stored directly inside NetBox objects.
#
# 3. Which module will use it next:
#    `import_devices()` and `import_interfaces()` inject this metadata into NetBox REST API calls.
#
# 4. What happens if this code is removed:
#    Interfaces created in NetBox will lack Port Security fields, breaking feature generation.
#
# 5. Real-world analogy:
#    Adding custom extra text boxes to a standard job application form for special credentials.
############################################################
def get_git_intent_data():
    import json
    intent_data = {}
    try:
        paths_to_try = [
            os.path.join(os.path.dirname(__file__), '../../csv/config_context'),
            os.path.join(os.getcwd(), 'csv/config_context'),
            os.path.join(os.getcwd(), 'enterprise_real_sot/csv/config_context')
        ]
        context_dir = None
        for p in paths_to_try:
            if os.path.exists(p):
                context_dir = p
                break
        if not context_dir:
            logger.error("Could not find csv/config_context directory")
            return {}

        devices_dir = os.path.join(context_dir, 'devices')
        if os.path.exists(devices_dir):
            for root, dirs, files in os.walk(devices_dir):
                for file in files:
                    if file.endswith('.csv'):
                        device_name = os.path.splitext(file)[0]
                        filepath = os.path.join(root, file)
                        device_data = {}
                        with open(filepath, 'r', encoding='utf-8') as f:
                            reader = csv.DictReader(f)
                            for row in reader:
                                if 'key' in row and 'value' in row and row['key']:
                                    k = row['key']
                                    v = row['value']
                                    try:
                                        device_data[k] = json.loads(v)
                                    except Exception:
                                        device_data[k] = v
                                elif 'data' in row and row.get('data'):
                                    try:
                                        parsed = json.loads(row['data'])
                                        if isinstance(parsed, dict):
                                            device_data.update(parsed)
                                    except Exception:
                                        pass
                        intent_data[device_name] = {"device": device_data}
    except Exception as e:
        logger.error(f"Failed to load CSV config contexts recursively: {e}")
    return intent_data


def resolve_vlan_by_vid(vid):
    res = api_get("ipam/vlans/", {"vid": vid})
    if res and res.get("results"):
        return res["results"][0]["id"]
    return None

def assign_interface_ip(address, interface_id):
    existing = api_get("ipam/ip-addresses/", {"address": address})
    ip_id = None
    if existing and existing.get("results"):
        ip_id = existing["results"][0]["id"]
    else:
        data = {
            "address": address,
            "status": "active"
        }
        res = api_post("ipam/ip-addresses/", data)
        if res:
            ip_id = res["id"]
            
    if ip_id:
        api_patch(f"ipam/ip-addresses/{ip_id}/", {
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": interface_id
        })

def ensure_custom_fields():
    res = api_get("extras/custom-fields/", {"name": "port_security"})
    if not res or not res.get("results"):
        logger.info("Creating custom field 'port_security' for dcim.interface...")
        data = {
            "object_types": ["dcim.interface"],
            "name": "port_security",
            "type": "json",
            "label": "Port Security"
        }
        api_post("extras/custom-fields/", data)

############################################################
# FUNCTION: import_devices()
#
# 1. Why this code exists:
#    Reads `devices.csv` and registers physical hardware switches/routers in NetBox.
#
# 2. What problem it solves:
#    Links physical devices to their foreign keys (Role ID, Device Type ID, Platform ID, Site ID, Rack ID)
#    and attaches device-local configuration context (`local_context_data`).
#
# 3. Which module will use it next:
#    `import_interfaces()` references these created devices by name to attach network ports.
#
# 4. What happens if this code is removed:
#    NetBox will contain no hardware inventory, halting downstream deployment pipelines.
#
# 5. Real-world analogy:
#    Registering company delivery trucks in a fleet management system with model, site location, and bay number.
############################################################
def import_devices():
    path = get_csv_path('devices.csv')
    rows = read_csv(path)
    intent_data = get_git_intent_data()
    for row in rows:
        existing = resolve_device(row['name'])
        
        device_raw = intent_data.get(row['name'], {}).get("device", {})
        local_context = {k: v for k, v in device_raw.items() if k != "interfaces"}
                
        role_id = resolve_device_role(row['device_role'])
        type_id = resolve_device_type(row['device_type'])
        platform_id = resolve_platform(row['platform'])
        site_id = resolve_site(row['site'])
        loc_id = resolve_location(row.get('location'))
        rack_id = resolve_rack(row.get('rack'), site_id)
        
        if not all([role_id, type_id, site_id]):
            logger.error(f"Cannot import device '{row['name']}': Missing dependencies (role, type, or site).")
            stats["failed"] += 1
            continue
            
        data = {
            "name": row['name'],
            "role": role_id,
            "device_type": type_id,
            "site": site_id,
            "status": row.get('status', 'active').lower(),
            "local_context_data": local_context
        }
        if platform_id:
            data["platform"] = platform_id
        if loc_id:
            data["location"] = loc_id
        if rack_id:
            data["rack"] = rack_id
        if row.get('position'):
            data["position"] = int(row['position'])
        if row.get('face'):
            data["face"] = row['face'].lower()
            
        if existing:
            logger.info(f"Device '{row['name']}' already exists. Updating (PATCH)...")
            api_patch(f"dcim/devices/{existing}/", data)
            stats["skipped"] += 1
        else:
            api_post("dcim/devices/", data)

############################################################
# FUNCTION: import_interfaces()
#
# 1. Why this code exists:
#    Imports network ports (Ethernet interfaces, VLAN interfaces, LAG Etherchannels),
#    configures switchport modes (Access / Tagged Trunk), resolves native/tagged VLANs,
#    attaches Port Security custom fields, assigns IPv6 addresses, and sets up LAG parent links.
#
# 2. What problem it solves:
#    Creates detailed port-level network topology inside NetBox.
#
# 3. Which module will use it next:
#    Deployment Layer (`ContextBuilder`) queries interface records to render Cisco switchport CLI.
#
# 4. What happens if this code is removed:
#    Devices will exist in NetBox as blank boxes without any network interfaces or switchport settings.
#
# 5. Real-world analogy:
#    Mapping out every electrical outlet in a building, marking whether it's 110V or 220V, and labeling which breaker room it connects to.
############################################################
def import_interfaces():
    path = get_csv_path('interfaces.csv')
    rows = read_csv(path)
    intent_data = get_git_intent_data()
    
    interface_id_map = {}
    for row in rows:
        device_id = resolve_device(row['device'])
        if not device_id:
            logger.error(f"Cannot import interface '{row['name']}': Device '{row['device']}' not found.")
            stats["failed"] += 1
            continue
            
        device_intent = intent_data.get(row['device'], {}).get("device", {})
        git_interfaces = device_intent.get("interfaces", [])
        git_intf = next((i for i in git_interfaces if i.get("name") == row['name']), {})
        
        import json
        git_mode = git_intf.get("mode") or row.get("mode")
        mode_val = None
        if git_mode == "access":
            mode_val = "access"
        elif git_mode == "tagged":
            mode_val = "tagged"
            
        untagged_vlan_id = None
        tagged_vlan_ids = []
        
        raw_untagged = git_intf.get("untagged_vlan") or git_intf.get("native_vlan") or row.get("untagged_vlan") or row.get("native_vlan")
        if raw_untagged:
            try:
                untagged_vlan_id = resolve_vlan_by_vid(int(raw_untagged))
            except Exception:
                pass
                
        raw_tagged = git_intf.get("tagged_vlans") or row.get("tagged_vlans")
        if raw_tagged:
            vids = []
            if isinstance(raw_tagged, list):
                vids = raw_tagged
            else:
                try:
                    vids = json.loads(raw_tagged)
                except Exception:
                    try:
                        vids = [int(v.strip()) for v in str(raw_tagged).split(",") if v.strip()]
                    except Exception:
                        pass
            for v in vids:
                try:
                    vid_resolved = resolve_vlan_by_vid(int(v))
                    if vid_resolved:
                        tagged_vlan_ids.append(vid_resolved)
                except Exception:
                    pass
                
        custom_fields = {}
        if "port_security" in git_intf:
            custom_fields["port_security"] = git_intf["port_security"]
            
        data = {
            "device": device_id,
            "name": row['name'],
            "type": row.get('type', '1000base-t').lower(),
            "enabled": row.get('enabled', 'true').lower() == 'true',
            "mgmt_only": row.get('mgmt_only', 'false').lower() == 'true',
            "description": git_intf.get("description") or row.get('description') or ""
        }
        if mode_val:
            data["mode"] = mode_val
        if untagged_vlan_id:
            data["untagged_vlan"] = untagged_vlan_id
        if tagged_vlan_ids:
            data["tagged_vlans"] = tagged_vlan_ids
        if custom_fields:
            data["custom_fields"] = custom_fields

        existing_res = api_get("dcim/interfaces/", {"device_id": device_id, "name": row['name']})
        intf_id = None
        if existing_res and existing_res.get("results"):
            existing_id = existing_res["results"][0]["id"]
            logger.info(f"Interface '{row['name']}' already exists on device '{row['device']}'. Updating (PATCH)...")
            api_patch(f"dcim/interfaces/{existing_id}/", data)
            intf_id = existing_id
            stats["skipped"] += 1
        else:
            res = api_post("dcim/interfaces/", data)
            if res:
                intf_id = res["id"]

        if intf_id:
            interface_id_map[(device_id, row['name'])] = intf_id
            if "ipv6" in git_intf and "addresses" in git_intf["ipv6"]:
                for addr in git_intf["ipv6"]["addresses"]:
                    logger.info(f"Assigning IPv6 {addr} to interface {row['name']}...")
                    assign_interface_ip(addr, intf_id)

    # Pass 2: Resolve and assign LAG parent relationships
    for row in rows:
        lag_name = row.get('lag')
        if lag_name:
            device_id = resolve_device(row['device'])
            if device_id:
                member_id = interface_id_map.get((device_id, row['name']))
                parent_id = interface_id_map.get((device_id, lag_name))
                if member_id and parent_id:
                    logger.info(f"Assigning member interface {row['name']} to LAG parent {lag_name} on {row['device']}...")
                    api_patch(f"dcim/interfaces/{member_id}/", {
                        "lag": parent_id
                    })

############################################################
# ORCHESTRATOR FUNCTION: run_dcim_import()
#
# 1. Why this code exists:
#    Main entry point function that runs all DCIM sub-importers in correct dependency order.
#
# 2. What problem it solves:
#    Ensures manufacturers and sites are created BEFORE devices, and devices are created BEFORE interfaces.
#
# 3. Which module will use it next:
#    `python/importers/run_import.py` calls `run_dcim_import()` as Stage 1 of the full import pipeline.
#
# 4. What happens if this code is removed:
#    The main import runner cannot execute DCIM data synchronization.
#
# 5. Real-world analogy:
#    A master construction schedule ensuring foundation, walls, electrical wiring, and paint happen in order.
############################################################
def run_dcim_import():
    logger.info("Starting DCIM import...")
    ensure_custom_fields()
    import_manufacturers()
    import_device_roles()
    import_platforms()
    import_device_types()
    import_regions()
    import_site_groups()
    import_sites()
    import_locations()
    import_racks()
    import_devices()
    import_interfaces()
    logger.info("DCIM import completed.")


