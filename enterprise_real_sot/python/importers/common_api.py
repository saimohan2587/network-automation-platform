"""
Purpose   : Core HTTP REST API client and ID resolution helper for NetBox importers.
Called By : import_dcim.py, import_ipam.py, import_config_context.py, run_import.py.
Calls Next: NetBox REST API endpoints (`/api/dcim/`, `/api/ipam/`, `/api/extras/`).
"""

############################################################
# WHY DOES THIS MODULE EXIST?
#
# NetBox is a relational network Source of Truth (SoT). When importing data from CSV
# files, python scripts must communicate with NetBox using HTTP REST API requests.
#
# This module (`common_api.py`) serves as the core utility foundation for the entire
# Import Layer. It manages HTTP sessions, authentication headers, error handling,
# statistics counters, and converts human-readable names (like site "hyderabad") into
# internal NetBox database IDs.
#
# REAL-WORLD ANALOGY:
# Imagine a translator at an international conference. The CSV file speaks "English"
# (human text names like "Cisco" or "Hyderabad"), while NetBox speaks "Database ID"
# (integer keys like Manufacturer #1, Site #4). This module acts as the translator
# and courier taking messages back and forth.
############################################################

import os
import sys
import requests
import logging

############################################################
# SYSTEM PATH SETUP & SETTINGS IMPORT
#
# 1. Why this code exists:
#    Ensures that the root project directory is added to Python's module search path
#    (`sys.path`), allowing this file to import `config.settings`. If `settings` cannot
#    be found, a `DummySettings` fallback class provides default connection parameters.
#
# 2. What problem it solves:
#    Prevents `ModuleNotFoundError` when executing importer scripts directly from different
#    working directories in terminal environments.
#
# 3. Which module will use it next:
#    `NETBOX_URL` and `NETBOX_TOKEN` are read immediately below to construct the HTTP session.
#
# 4. What happens if this code is removed:
#    Python won't find the configuration file, causing import errors or failing to authenticate with NetBox.
#
# 5. Real-world analogy:
#    Like setting the home address on a GPS before starting a delivery truck route.
############################################################
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
try:
    import config.settings as settings
except ImportError:
    class DummySettings:
        NETBOX_URL = os.getenv("NETBOX_URL", "http://localhost:8000")
        NETBOX_TOKEN = os.getenv("NETBOX_TOKEN", "")
        CSV_DIR = os.getenv("CSV_DIR", "./csv")
    settings = DummySettings()

############################################################
# LOGGING SETUP & GLOBAL IMPORT STATISTICS
#
# 1. Why this code exists:
#    Configures the `NetBoxImporter` log format and initializes a global `stats`
#    dictionary (`created`, `skipped`, `failed`) to track import progress.
#
# 2. What problem it solves:
#    Gives system administrators real-time visibility into how many objects succeeded
#    or failed during large-scale CSV imports.
#
# 3. Which module will use it next:
#    `api_post` increments these numbers, and `run_import.py` prints the final summary at the end.
#
# 4. What happens if this code is removed:
#    The import job would run "in the dark" without giving feedback on how many objects were processed.
#
# 5. Real-world analogy:
#    Like a scoreboard at a sports stadium keeping live count of points scored and fouls committed.
############################################################
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("NetBoxImporter")

stats = {
    "created": 0,
    "skipped": 0,
    "failed": 0
}

############################################################
# PERSISTENT HTTP SESSION & AUTHENTICATION HEADERS
#
# 1. Why this code exists:
#    Creates a reusable `requests.Session()` object pre-loaded with the NetBox API token
#    (`Authorization: Token ...`) and JSON headers.
#
# 2. What problem it solves:
#    Performance optimization! Instead of opening a new TCP connection for every single
#    CSV record, a `requests.Session` reuses the underlying connection (HTTP Keep-Alive),
#    making imports up to 10x faster.
#
# 3. Which module will use it next:
#    `api_get`, `api_post`, and `api_patch` use this session for all HTTP requests.
#
# 4. What happens if this code is removed:
#    Every HTTP call would fail with "401 Unauthorized" because NetBox requires valid token headers.
#
# 5. Real-world analogy:
#    Like showing your security badge once at the front gate to get a visitor wristband,
#    rather than presenting your passport at every single doorway inside the building.
############################################################
session = requests.Session()
session.headers.update({
    "Authorization": f"Token {settings.NETBOX_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
})

############################################################
# FUNCTION: get_netbox_url()
#
# 1. Why this code exists:
#    Safely concatenates `NETBOX_URL` with specific NetBox REST API endpoint paths.
#
# 2. What problem it solves:
#    Prevents double slashes (e.g., `http://localhost:8000/api//dcim/devices/`) or
#    missing slashes that lead to 404 HTTP errors.
#
# 3. Which module will use it next:
#    Called internally by `api_get`, `api_post`, and `api_patch`.
#
# 4. What happens if this code is removed:
#    API requests would hit malformed URLs and crash.
#
# 5. Real-world analogy:
#    Like an address formatter that adds zip codes and country names so mail isn't misrouted.
############################################################
def get_netbox_url(endpoint):
    return f"{settings.NETBOX_URL.rstrip('/')}/api/{endpoint.lstrip('/')}"

############################################################
# HTTP CRUD HELPER FUNCTIONS: api_get, api_post, api_patch
#
# 1. Why this code exists:
#    Provides safe wrapper functions around HTTP GET, POST, and PATCH verbs.
#
# 2. What problem it solves:
#    Centralizes error handling (try/except), status code verification (200/201 vs errors),
#    and statistics updates so individual importer scripts don't duplicate code.
#
# 3. Which module will use it next:
#    Called by `import_dcim.py`, `import_ipam.py`, `import_config_context.py`, and `run_import.py`.
#
# 4. What happens if this code is removed:
#    Importer scripts would have to write 15+ lines of raw `requests` boilerplate for every single API call.
#
# 5. Real-world analogy:
#    Like using a dedicated mailroom service: you hand them your document (POST/PATCH/GET), and they handle
#    postage, tracking receipts, and error notifications.
############################################################
def api_get(endpoint, params=None):
    url = get_netbox_url(endpoint)
    try:
        response = session.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to GET {url} with params {params}: {e}")
        return None

def api_post(endpoint, data):
    url = get_netbox_url(endpoint)
    try:
        response = session.post(url, json=data, timeout=10)
        if response.status_code in [200, 201]:
            stats["created"] += 1
            return response.json()
        else:
            logger.error(f"Failed to POST {url}: {response.status_code} - {response.text}")
            stats["failed"] += 1
            return None
    except Exception as e:
        logger.error(f"Exception during POST to {url}: {e}")
        stats["failed"] += 1
        return None

def api_patch(endpoint, data):
    url = get_netbox_url(endpoint)
    try:
        response = session.patch(url, json=data, timeout=10)
        if response.status_code in [200, 204]:
            return response.json()
        else:
            logger.error(f"Failed to PATCH {url}: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Exception during PATCH to {url}: {e}")
        return None

############################################################
# RESOURCE RESOLUTION HELPERS (Name/Slug -> Database ID)
#
# 1. Why this code exists:
#    In NetBox relational databases, objects (like a Device) connect to other objects
#    (like a Site or Manufacturer) using integer IDs (e.g. `site_id: 4`). However, CSV
#    files contain human-readable text slugs/names (e.g. `site: "hyderabad"`).
#
# 2. What problem it solves:
#    Queries NetBox REST API to convert text slugs/names from CSV files into numeric IDs.
#
# 3. Which module will use it next:
#    `import_dcim.py`, `import_ipam.py`, and `import_config_context.py` call these helpers
#    before attaching devices to sites, interfaces to devices, or IPs to interfaces.
#
# 4. What happens if this code is removed:
#    NetBox API will reject imports with HTTP 400 validation errors because text strings cannot
#    be assigned to database relational foreign keys.
#
# 5. Real-world analogy:
#    Like looking up a person's employee ID number in HR directory using their name before submitting an expense report.
############################################################
def resolve_by_slug(endpoint, slug):
    if not slug:
        return None
    res = api_get(endpoint, {"slug": slug})
    if res and res.get("results"):
        return res["results"][0]["id"]
    return None

def resolve_by_name(endpoint, name):
    if not name:
        return None
    res = api_get(endpoint, {"name": name})
    if res and res.get("results"):
        return res["results"][0]["id"]
    return None

def resolve_region(slug):
    return resolve_by_slug("dcim/regions/", slug)

def resolve_site_group(slug):
    return resolve_by_slug("dcim/site-groups/", slug)

def resolve_site(slug):
    return resolve_by_slug("dcim/sites/", slug)

def resolve_location(slug):
    return resolve_by_slug("dcim/locations/", slug)

def resolve_manufacturer(slug):
    return resolve_by_slug("dcim/manufacturers/", slug)

def resolve_device_role(slug):
    return resolve_by_slug("dcim/device-roles/", slug)

def resolve_platform(slug):
    return resolve_by_slug("dcim/platforms/", slug)

def resolve_device_type(slug):
    return resolve_by_slug("dcim/device-types/", slug)

def resolve_rack(name, site_id):
    if not name:
        return None
    res = api_get("dcim/racks/", {"name": name, "site_id": site_id})
    if res and res.get("results"):
        return res["results"][0]["id"]
    return None

def resolve_device(name):
    return resolve_by_name("dcim/devices/", name)

