"""
Purpose   : Reads key-value configuration CSVs (global defaults, site overrides) and imports them into NetBox Config Contexts.
Called By : run_import.py (`run_config_context_import()`).
Calls Next: NetBox REST API (`/api/extras/config-contexts/`) via common_api.py.
"""

import os
import csv
import json
import logging
from common_api import (
    api_post, api_patch, api_get, resolve_site, stats
)

logger = logging.getLogger("NetBoxImporter")

# Input: CSV file path | Processing: Converts key-value CSV rows into a Python dictionary | Output: Formatted context dictionary.
def load_csv_context(filepath):
    data = {}
    if not os.path.exists(filepath):
        logger.warning(f"Config context path not found: {filepath}")
        return data
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                k = row['key']
                v = row['value']
                try:
                    data[k] = json.loads(v)
                except Exception:
                    data[k] = v
    except Exception as e:
        logger.error(f"Failed to parse CSV context from {filepath}: {e}")
    return data

# Reads global and site-level CSV settings and pushes them into NetBox Config Context objects.
def run_config_context_import():
    logger.info("Starting Config Context import from CSV...")
    
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
        logger.error("Could not find config_context directory")
        stats["failed"] += 1
        return

    # 1. Import Global Config Context
    try:
        global_path = os.path.join(context_dir, 'global/global_defaults.csv')
        global_data = load_csv_context(global_path)
        context_name = "Global-Defaults"
        existing = api_get("extras/config-contexts/", {"name": context_name})
        
        data = {
            "name": context_name,
            "data": global_data,
            "description": "Global Enterprise baseline configuration defaults"
        }
        
        if existing and existing.get("results"):
            existing_id = existing["results"][0]["id"]
            logger.info(f"Config Context '{context_name}' already exists. Updating (PATCH)...")
            api_patch(f"extras/config-contexts/{existing_id}/", data)
            stats["skipped"] += 1
        else:
            api_post("extras/config-contexts/", data)
    except Exception as e:
        logger.error(f"Failed to import global config context: {e}")
        stats["failed"] += 1

    # 2. Import Site-level Config Contexts
    sites_dir = os.path.join(context_dir, "sites")
    if os.path.exists(sites_dir):
        for filename in os.listdir(sites_dir):
            if filename.endswith('.csv'):
                site_slug = os.path.splitext(filename)[0]
                try:
                    site_data = load_csv_context(os.path.join(sites_dir, filename))
                    site_id = resolve_site(site_slug)
                    if not site_id:
                        logger.error(f"Cannot scope site config context: Site '{site_slug}' not found in NetBox.")
                        stats["failed"] += 1
                        continue
                    
                    cleaned_data = {
                        k: v for k, v in site_data.items()
                        if k not in ["site", "locations", "racks", "vlans", "prefixes"]
                    }
                    
                    context_name = f"Site-Defaults-{site_slug}"
                    existing = api_get("extras/config-contexts/", {"name": context_name})
                    
                    data = {
                        "name": context_name,
                        "data": cleaned_data,
                        "sites": [site_id],
                        "description": f"Site-specific overrides for site {site_slug.upper()}"
                    }
                    
                    if existing and existing.get("results"):
                        existing_id = existing["results"][0]["id"]
                        logger.info(f"Config Context '{context_name}' already exists. Updating (PATCH)...")
                        api_patch(f"extras/config-contexts/{existing_id}/", data)
                        stats["skipped"] += 1
                    else:
                        api_post("extras/config-contexts/", data)
                except Exception as e:
                    logger.error(f"Failed to import site config context for '{site_slug}': {e}")
                    stats["failed"] += 1

    # 3. Cleanup obsolete config contexts
    logger.info("Cleaning up obsolete per-protocol config contexts...")
    existing_contexts = api_get("extras/config-contexts/")
    if existing_contexts and existing_contexts.get("results"):
        for context in existing_contexts["results"]:
            name = context["name"]
            if name.startswith("sw-access-01-"):
                cid = context["id"]
                logger.info(f"Deleting obsolete config context: {name}")
                from common_api import session, get_netbox_url
                url = get_netbox_url(f"extras/config-contexts/{cid}/")
                try:
                    response = session.delete(url, timeout=10)
                    if response.status_code in [200, 204]:
                        logger.info(f"Obsolete config context {name} deleted successfully.")
                    else:
                        logger.error(f"Failed to delete obsolete config context {name}: {response.text}")
                except Exception as e:
                    logger.error(f"Exception during deletion of config context {name}: {e}")

    logger.info("Config Context import completed.")
