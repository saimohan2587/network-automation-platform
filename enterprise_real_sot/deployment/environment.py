"""
Purpose   : Resolves the target deployment environment (staging vs. production) for a network device
            using NetBox DCIM tags, custom fields, config context, IPAM prefixes, and role metadata.
Called By : deployment/main.py, deployment/cli.py, and tollgate validation tests.
"""

from typing import Any, Mapping, Optional
import ipaddress


# Subnet ranges mapped to environments according to IPAM architecture
STAGING_PREFIXES = [
    ipaddress.ip_network("10.10.10.0/24"),  # R1 Gateway & Transit
    ipaddress.ip_network("10.10.20.0/24"),  # SW1Staging
    ipaddress.ip_network("10.10.30.0/24"),  # SW2Staging
    ipaddress.ip_network("10.10.80.0/24"),  # SW3Staging
]

PRODUCTION_PREFIXES = [
    ipaddress.ip_network("10.10.40.0/24"),  # SW1Prod
    ipaddress.ip_network("10.10.50.0/24"),  # SW2Prod
    ipaddress.ip_network("10.10.60.0/24"),  # SW3Prod
    ipaddress.ip_network("10.10.70.0/24"),  # R2 Gateway & Transit
]


def resolve_device_environment(
    device_record: Optional[Mapping[str, Any]] = None,
    manifest_device: Optional[Mapping[str, Any]] = None,
) -> str:
    """
    Identifies whether a device belongs to 'staging' or 'production' using
    hierarchical inventory metadata from NetBox, IPAM, and configuration intent.
    Never relies solely on device names.

    Hierarchy:
    1. NetBox Device Tags ('staging' vs. 'production')
    2. NetBox Custom Fields ('environment' / 'env')
    3. NetBox Config Context ('environment')
    4. NetBox Primary IP / IPAM subnet classification
    5. NetBox Site / Tenant / Description metadata
    6. Hostname convention fallback
    """
    device_record = device_record or {}
    manifest_device = manifest_device or {}

    # 1. NetBox Device Tags
    tags = device_record.get("tags") or []
    for tag in tags:
        if isinstance(tag, Mapping):
            tag_vals = [
                str(tag.get("slug") or "").lower(),
                str(tag.get("name") or "").lower(),
            ]
        else:
            tag_vals = [str(tag).lower()]
        for val in tag_vals:
            if val in ("staging", "stage", "test", "lab", "non-prod"):
                return "staging"
            if val in ("production", "prod", "live"):
                return "production"

    # 2. NetBox Custom Fields
    custom_fields = device_record.get("custom_fields") or {}
    if isinstance(custom_fields, Mapping):
        env_cf = str(custom_fields.get("environment") or custom_fields.get("env") or "").lower()
        if "stag" in env_cf or env_cf in ("test", "lab"):
            return "staging"
        if "prod" in env_cf:
            return "production"

    # 3. NetBox Config Context / Local Context Data
    local_context = device_record.get("local_context_data") or device_record.get("config_context") or {}
    if isinstance(local_context, Mapping):
        env_ctx = str(local_context.get("environment") or local_context.get("env") or "").lower()
        if "stag" in env_ctx or env_ctx in ("test", "lab"):
            return "staging"
        if "prod" in env_ctx:
            return "production"

    # 4. NetBox Primary IP / Management IP Subnet
    ip_str = ""
    primary_ip = device_record.get("primary_ip")
    if isinstance(primary_ip, Mapping):
        ip_str = primary_ip.get("address") or ""
    elif isinstance(primary_ip, str):
        ip_str = primary_ip

    if not ip_str and manifest_device.get("ip_address"):
        ip_str = str(manifest_device.get("ip_address"))

    if ip_str:
        clean_ip = ip_str.split("/")[0].strip()
        try:
            ip_obj = ipaddress.ip_address(clean_ip)
            for net in STAGING_PREFIXES:
                if ip_obj in net:
                    return "staging"
            for net in PRODUCTION_PREFIXES:
                if ip_obj in net:
                    return "production"
        except ValueError:
            pass

    # 5. NetBox Site / Tenant / Description Metadata
    site_obj = device_record.get("site") or {}
    site_slug = str(site_obj.get("slug") or "") if isinstance(site_obj, Mapping) else str(site_obj or "")
    site_slug = site_slug.lower()
    if "staging" in site_slug or "stage" in site_slug:
        return "staging"
    if "production" in site_slug or "prod" in site_slug:
        return "production"

    description = str(device_record.get("description") or "").lower()
    if "[staging]" in description or "staging" in description:
        return "staging"
    if "[production]" in description or "production" in description:
        return "production"

    # 6. Hostname Pattern Fallback
    name = (
        device_record.get("name")
        or manifest_device.get("device_name")
        or ""
    ).lower()

    if "staging" in name or name == "r1":
        return "staging"
    if "prod" in name or name == "r2":
        return "production"

    return "unknown"
