"""ServiceNow Integration Configuration Settings.

Externalizes credentials and environment variables for ServiceNow REST API integration.
Automatically loads environment variables from enterprise_real_sot/.env file.
Supports live ServiceNow Table API calls or mock staging mode fallback.
"""

import os
from pathlib import Path

# Base Directory Paths
BASE_DIR = Path(__file__).resolve().parent.parent
SOT_DIR = BASE_DIR.parent
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
INCIDENT_STORE_FILE = STORAGE_DIR / "incidents.json"


def _load_dotenv():
    """Helper to parse enterprise_real_sot/.env without external dependencies."""
    env_file = SOT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"").replace("$$", "$")
                if key not in os.environ:
                    os.environ[key] = val



_load_dotenv()

# ServiceNow Instance Credentials
SERVICENOW_INSTANCE_URL = os.getenv("SERVICENOW_INSTANCE_URL", "https://dev388799.service-now.com").rstrip("/")
SERVICENOW_USERNAME = os.getenv("SERVICENOW_USERNAME", "admin")
SERVICENOW_PASSWORD = os.getenv("SERVICENOW_PASSWORD", "")
SERVICENOW_TIMEOUT = int(os.getenv("SERVICENOW_TIMEOUT", "60"))

# sys_id of the ServiceNow user incident payloads are filed under. Previously
# hardcoded directly in servicenow/models/incident_payload.py; now sourced
# from the environment so a real deployment can point this at a dedicated
# least-privilege service account instead of "System Administrator".
SERVICENOW_CALLER_ID_SYS_ID = os.getenv("SERVICENOW_CALLER_ID_SYS_ID", "6816f79cc0a8016401c5a33be04be441")



# Centralized Device Role -> Assignment Group Mapping.
# Routes on the alert's device_role label (e.g. "router", "access") rather than
# hardcoded device names, so newly added devices route correctly without code changes.
ASSIGNMENT_GROUPS_BY_ROLE = {
    "router": "Network Routing",
    "routing": "Network Routing",
    "access": "Network Switching",
    "switch": "Network Switching",
    "access_switch": "Network Switching",
    "switching": "Network Switching",
}
DEFAULT_ASSIGNMENT_GROUP = "Network Operations Center"

# Substring fallback for compound role slugs the exact-match table above doesn't
# enumerate (e.g. NetBox-style "l3-gateway-router", "layer-2-access-switch",
# "core-switch", "distribution-switch", or a future "edge-router"). Checked in
# this order (routing before switching) only when no exact match is found.
_ASSIGNMENT_GROUP_SUBSTRING_FALLBACK = (
    ("router", "Network Routing"),
    ("routing", "Network Routing"),
    ("switch", "Network Switching"),
    ("access", "Network Switching"),
)


def resolve_assignment_group(device_role: str) -> str:
    """
    Map a device_role string to a ServiceNow assignment group.

    Tries an exact match against ASSIGNMENT_GROUPS_BY_ROLE first (fast path,
    covers this project's known lab/GNS3 role slugs exactly as-is). Falls back
    to substring matching for compound role slugs that contain a recognized
    token (e.g. "layer-2-access-switch" contains "switch"; "l3-gateway-router"
    and "edge_router" both contain "router") - the same pattern already used by
    deployment/capability_resolver.py for the identical problem, applied here
    for consistency rather than growing the exact-match table indefinitely.
    """
    role_lower = device_role.lower()

    exact = ASSIGNMENT_GROUPS_BY_ROLE.get(role_lower)
    if exact is not None:
        return exact

    for token, group in _ASSIGNMENT_GROUP_SUBSTRING_FALLBACK:
        if token in role_lower:
            return group

    return DEFAULT_ASSIGNMENT_GROUP


# Explicit Mock Mode toggle or automatic fallback if password missing
_explicit_mock = os.getenv("SERVICENOW_MOCK_MODE", "").lower()
if _explicit_mock in ("false", "0", "no") and SERVICENOW_PASSWORD:
    SERVICENOW_MOCK_MODE = False
elif _explicit_mock in ("true", "1", "yes"):
    SERVICENOW_MOCK_MODE = True
else:
    # Disable mock mode if password exists, enable if missing
    SERVICENOW_MOCK_MODE = not bool(SERVICENOW_PASSWORD)

# Webhook Server Settings
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8000"))
