"""
Purpose   : Imports IP addresses, subnets, and VLANs from CSV into NetBox IPAM and binds management IPs to switch interfaces.
Called By : run_import.py (`run_ipam_import()`).
Calls Next: NetBox REST API (`/api/ipam/`) via common_api.py.
"""

############################################################
# WHY DOES THIS MODULE EXIST?
#
# IPAM stands for IP Address Management. In enterprise networks, keeping track of
# VLANs (Layer 2 broadcast domains), Subnet Prefixes (Layer 3 IP ranges), and individual
# IP Addresses (assigned to switch interfaces and management ports) is critical.
#
# This module (`import_ipam.py`) reads CSV files from `csv/ipam/` and populates NetBox's
# IPAM database, binding IP addresses directly to physical device interfaces and setting
# primary management IPs.
#
# REAL-WORLD ANALOGY:
# Imagine a city phone directory. Prefixes are like area codes (040 for Hyderabad),
# VLANs are like neighborhood departments, and IP addresses are individual phone numbers
# assigned to specific desks (interfaces) in an office building.
############################################################

import os
import csv
import logging
from common_api import (
    api_get, api_post, api_patch, resolve_device, stats
)

logger = logging.getLogger("NetBoxImporter")

############################################################
# CSV PATH & READING HELPERS
#
# 1. Why this code exists:
#    Searches multiple relative directories to locate `vlans.csv`, `prefixes.csv`,
#    and `ip_addresses.csv`, converting raw CSV rows into Python dictionaries.
#
# 2. What problem it solves:
#    Ensures scripts locate input files regardless of the current working directory.
#
# 3. Which module will use it next:
#    `import_vlans()`, `import_prefixes()`, and `import_ip_addresses_and_assign()`.
#
# 4. What happens if this code is removed:
#    IPAM import functions will fail to locate or parse CSV data.
#
# 5. Real-world analogy:
#    A librarian checking multiple catalog drawers to find the requested ledger book.
############################################################
def get_csv_path(filename):
    paths_to_try = [
        os.path.join(os.path.dirname(__file__), '../../csv/ipam', filename),
        os.path.join(os.getcwd(), 'csv/ipam', filename),
        os.path.join(os.getcwd(), 'enterprise_real_sot/csv/ipam', filename)
    ]
    for p in paths_to_try:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"Could not find IPAM CSV file: {filename}")

def read_csv(path):
    if not os.path.exists(path):
        logger.error(f"CSV file not found: {path}")
        return []
    with open(path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return [row for row in reader]

############################################################
# FUNCTION: import_vlans()
#
# 1. Why this code exists:
#    Reads `vlans.csv` and creates VLAN records (e.g. VID 10 = Finance, VID 20 = Engineering) in NetBox.
#
# 2. What problem it solves:
#    Establishes Layer-2 broadcast domain definitions in NetBox before switch interfaces reference them.
#
# 3. Which module will use it next:
#    `import_interfaces()` in `import_dcim.py` resolves these VLAN IDs to assign switchport access/tagged VLANs.
#
# 4. What happens if this code is removed:
#    Switchports created in NetBox won't be able to bind to valid VLAN objects.
#
# 5. Real-world analogy:
#    Assigning official department code numbers (e.g., Dept 10 = Accounting, Dept 20 = IT) in HR software.
############################################################
def import_vlans():
    path = get_csv_path('vlans.csv')
    rows = read_csv(path)
    for row in rows:
        vid = int(row['vid'])
        existing = api_get("ipam/vlans/", {"vid": vid})
        if existing and existing.get("results"):
            logger.info(f"VLAN {vid} already exists. Skipping.")
            stats["skipped"] += 1
            continue
        data = {
            "vid": vid,
            "name": row['name'],
            "status": row.get('status', 'active').lower(),
            "description": row.get('description', '')
        }
        api_post("ipam/vlans/", data)

############################################################
# FUNCTION: import_prefixes()
#
# 1. Why this code exists:
#    Reads `prefixes.csv` and registers Subnet Prefixes (e.g. `10.10.1.0/24`, `192.168.10.0/24`) in NetBox.
#
# 2. What problem it solves:
#    Documents network address space allocation, preventing IP overlap and subnet exhaustion across enterprise sites.
#
# 3. Which module will use it next:
#    NetBox IPAM hierarchy and `ContextBuilder` query subnet prefixes during context generation.
#
# 4. What happens if this code is removed:
#    NetBox won't track IP subnet allocations or parent-child network hierarchy.
#
# 5. Real-world analogy:
#    Reserving a block of ZIP codes or phone exchange prefixes for a new city district.
############################################################
def import_prefixes():
    path = get_csv_path('prefixes.csv')
    rows = read_csv(path)
    for row in rows:
        prefix = row['prefix']
        existing = api_get("ipam/prefixes/", {"prefix": prefix})
        if existing and existing.get("results"):
            logger.info(f"Prefix {prefix} already exists. Skipping.")
            stats["skipped"] += 1
            continue
        data = {
            "prefix": prefix,
            "status": row.get('status', 'active').lower(),
            "description": row.get('description', '')
        }
        api_post("ipam/prefixes/", data)

############################################################
# FUNCTION: import_ip_addresses_and_assign()
#
# 1. Why this code exists:
#    Reads `ip_addresses.csv`, creates IP address objects (e.g., `192.168.10.1/24`), assigns
#    them to specific device interfaces (`dcim.interface`), and sets primary IPv4 addresses on devices.
#
# 2. What problem it solves:
#    Binds IP addresses directly to physical/virtual switch interfaces and establishes the
#    primary management IP used for SSH remote management.
#
# 3. Which module will use it next:
#    Deployment Layer (`DeviceSelector` and `DeviceConnector`) queries `primary_ip4` from NetBox
#    to target the switch over SSH.
#
# 4. What happens if this code is removed:
#    Switches in NetBox will lack IP addresses and primary management IPs, breaking automated deployment connections.
#
# 5. Real-world analogy:
#    Assigning a direct phone number extension to an employee's desk telephone and setting it as their primary contact number.
############################################################
def import_ip_addresses_and_assign():
    path = get_csv_path('ip_addresses.csv')
    rows = read_csv(path)
    
    for row in rows:
        address = row['address']
        dev_name = row.get('device', 'sw-access-01')
        iface_name = row.get('interface', 'Vlan100')
        role_type = row.get('role', 'primary')
        
        device_id = resolve_device(dev_name)
        if not device_id:
            logger.error(f"Cannot assign IP address {address}: Device '{dev_name}' not found.")
            stats["failed"] += 1
            continue

        if_res = api_get("dcim/interfaces/", {"device_id": device_id, "name": iface_name})
        if not if_res or not if_res.get("results"):
            logger.error(f"Cannot assign IP address {address}: Interface '{iface_name}' not found on '{dev_name}'.")
            stats["failed"] += 1
            continue
        interface_id = if_res["results"][0]["id"]

        existing = api_get("ipam/ip-addresses/", {"address": address})
        
        ip_id = None
        if existing and existing.get("results"):
            logger.info(f"IP Address {address} already exists.")
            ip_id = existing["results"][0]["id"]
            stats["skipped"] += 1
        else:
            data = {
                "address": address,
                "status": row.get('status', 'active').lower(),
                "description": row.get('description', '')
            }
            res = api_post("ipam/ip-addresses/", data)
            if res:
                ip_id = res["id"]

        if ip_id:
            # Assign IP to interface
            logger.info(f"Assigning IP {address} to interface {iface_name} on {dev_name} (ID: {interface_id})...")
            api_patch(f"ipam/ip-addresses/{ip_id}/", {
                "assigned_object_type": "dcim.interface",
                "assigned_object_id": interface_id
            })
            
            # Set as Primary IPv4 on Device if role is primary
            if role_type == "primary" and ":" not in address:
                logger.info(f"Setting primary IPv4 on device '{dev_name}' to IP ID {ip_id}...")
                api_patch(f"dcim/devices/{device_id}/", {
                    "primary_ip4": ip_id
                })

############################################################
# ORCHESTRATOR FUNCTION: run_ipam_import()
#
# 1. Why this code exists:
#    Sequential runner that executes `import_vlans()`, `import_prefixes()`, and `import_ip_addresses_and_assign()`.
#
# 2. What problem it solves:
#    Guarantees correct order so VLANs and prefixes exist before IPs are assigned.
#
# 3. Which module will use it next:
#    `python/importers/run_import.py` calls `run_ipam_import()` as Stage 2 of full import.
#
# 4. What happens if this code is removed:
#    IPAM synchronization cannot be executed.
#
# 5. Real-world analogy:
#    An office setup manager making sure room numbers and telephone lines exist before handing out employee extensions.
############################################################
def run_ipam_import():
    logger.info("Starting IPAM import...")
    import_vlans()
    import_prefixes()
    import_ip_addresses_and_assign()
    logger.info("IPAM import completed.")

