"""
Purpose   : Master orchestrator script to read CSV network data and import it into NetBox (Source of Truth).
Called By : Direct user invocation (`python run_import.py`).
Calls Next: import_dcim.py -> import_ipam.py -> import_config_context.py.
"""

import os
import sys
import logging

# Add current folder and project root to path
sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from common_api import api_get, resolve_device, stats
from import_dcim import run_dcim_import
from import_ipam import run_ipam_import
from import_config_context import run_config_context_import

logger = logging.getLogger("NetBoxImporter")


# Verifies that required hardware, IP addresses, and contexts were correctly populated in NetBox.
def run_validation():
    logger.info("Running validation of imported objects...")
    
    validation_status = {
        "Manufacturers": "FAIL",
        "Platforms": "FAIL",
        "Device Types": "FAIL",
        "Devices": "FAIL",
        "Interfaces": "FAIL",
        "VLANs": "FAIL",
        "Prefixes": "FAIL",
        "IP Addresses": "FAIL",
        "IP Assignment": "FAIL",
        "Primary IPv4": "FAIL",
        "Config Contexts": "FAIL"
    }

    # Verify Manufacturer
    mfg = api_get("dcim/manufacturers/", {"slug": "cisco"})
    if mfg and mfg.get("count", 0) > 0:
        validation_status["Manufacturers"] = "OK"

    # Verify Platform
    plat = api_get("dcim/platforms/", {"slug": "cisco-ios"})
    if plat and plat.get("count", 0) > 0:
        validation_status["Platforms"] = "OK"

    # Verify Device Type
    dtype = api_get("dcim/device-types/", {"slug": "ws-c3750x-24p"})
    if dtype and dtype.get("count", 0) > 0:
        validation_status["Device Types"] = "OK"

    # Verify Device
    dev_id = resolve_device("sw-access-01")
    if dev_id:
        validation_status["Devices"] = "OK"

        # Verify Interfaces
        interfaces = api_get("dcim/interfaces/", {"device_id": dev_id})
        if interfaces and interfaces.get("count", 0) > 0:
            validation_status["Interfaces"] = "OK"

        # Verify Config Contexts
        contexts = api_get("extras/config-contexts/", {"device_id": dev_id})
        if contexts and contexts.get("count", 0) > 0:
            validation_status["Config Contexts"] = "OK"

    # Verify VLAN
    vlan = api_get("ipam/vlans/", {"vid": 100})
    if vlan and vlan.get("count", 0) > 0:
        validation_status["VLANs"] = "OK"

    # Verify Prefix
    prefix = api_get("ipam/prefixes/", {"prefix": "192.168.1.0/24"})
    if prefix and prefix.get("count", 0) > 0:
        validation_status["Prefixes"] = "OK"

    # Verify IP Address & Assignment & Primary IP
    ip_res = api_get("ipam/ip-addresses/", {"address": "192.168.1.20/24"})
    if ip_res and ip_res.get("count", 0) > 0:
        validation_status["IP Addresses"] = "OK"
        ip_obj = ip_res["results"][0]
        
        # Verify it is assigned to Vlan100 interface
        assigned_obj = ip_obj.get("assigned_object")
        if assigned_obj and assigned_obj.get("name") == "Vlan100":
            validation_status["IP Assignment"] = "OK"
            
        # Verify it is set as Primary IPv4 on device
        if dev_id:
            dev_res = api_get(f"dcim/devices/{dev_id}/")
            if dev_res:
                prim_ip = dev_res.get("primary_ip4") or dev_res.get("primary_ip")
                if prim_ip and prim_ip.get("address") == "192.168.1.20/24":
                    validation_status["Primary IPv4"] = "OK"

    print("\n--- Validation Summary ---")
    for key, status in validation_status.items():
        print(f"{key:<15} : {status}")
    print("--------------------------\n")

# Main execution loop to run DCIM, IPAM, and Config Context imports sequentially.
def main():
    logger.info("Starting NetBox import orchestration...")
    
    # Reset stats
    stats["created"] = 0
    stats["skipped"] = 0
    stats["failed"] = 0
    
    try:
        # Import physical hardware inventory, racks, devices, and interfaces into NetBox (import_dcim.py).
        run_dcim_import()
        # Import IP subnets, VLANs, and IP assignments into NetBox IPAM (import_ipam.py).
        run_ipam_import()
        # Import feature intent data into NetBox Config Contexts (import_config_context.py).
        run_config_context_import()
        # Run verification checks against NetBox REST API.
        run_validation()
    except Exception as e:
        logger.exception(f"Import process failed with exception: {e}")
        stats["failed"] += 1

    print("\n--- Import Summary ---")
    print(f"Objects Created                  : {stats['created']}")
    print(f"Objects Skipped (Already Exists) : {stats['skipped']}")
    print(f"Objects Failed                   : {stats['failed']}")
    print("----------------------\n")

if __name__ == "__main__":
    main()

