import os

def _load_env_file():
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k:
                        os.environ[k] = v

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    _load_env_file()

# Read NetBox URL from environment variables, fallback to localhost. Normalize so it always ends with a single "/".
NETBOX_URL = os.getenv("NETBOX_URL", "http://localhost:8000/api/").rstrip("/") + "/"
# Read NetBox API authentication token from environment variables.
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN", "")

# Read HTTP request timeout in seconds. Prevents HTTP client from hanging indefinitely if server freezes.
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", 15))
# Read maximum HTTP retry count for handling transient 50x server errors.
HTTP_MAX_RETRIES = int(os.getenv("HTTP_MAX_RETRIES", 3))
# Read backoff factor controlling sleep delay between HTTP retry attempts.
HTTP_BACKOFF_FACTOR = float(os.getenv("HTTP_BACKOFF_FACTOR", 0.5))

# Read default SSH port for network device transport connections.
SSH_PORT = int(os.getenv("SSH_PORT", 22))
# Read default SSH socket timeout in seconds.
SSH_TIMEOUT = int(os.getenv("SSH_TIMEOUT", 30))
# Read default SSH username for network device authentication.
SSH_USERNAME = os.getenv("SSH_USERNAME", "admin")
# Read default SSH password for network device authentication.
SSH_PASSWORD = os.getenv("SSH_PASSWORD", "")
# Read default SSH enable secret for network device authentication.
SSH_SECRET = os.getenv("SSH_SECRET", os.getenv("SSH_PASSWORD", ""))

# Read maximum concurrent worker threads allowed during parallel multi-device rollouts.
MAX_WORKER_THREADS = int(os.getenv("MAX_WORKER_THREADS", 10))


def get_profile_credentials(profile_name: str) -> dict:
    """Retrieve SSH credentials for a specific profile name from environment variables.

    Lookup order:
    1. SSH_<PROFILE>_USERNAME / SSH_<PROFILE>_PASSWORD / SSH_<PROFILE>_SECRET
    2. Fallback to default SSH_USERNAME / SSH_PASSWORD / SSH_SECRET
    """
    prefix = f"SSH_{profile_name.upper().replace('-', '_')}_"
    username = os.getenv(f"{prefix}USERNAME", SSH_USERNAME)
    password = os.getenv(f"{prefix}PASSWORD", SSH_PASSWORD)
    secret = os.getenv(f"{prefix}SECRET", os.getenv(f"{prefix}PASSWORD", SSH_SECRET))
    return {
        "username": username,
        "password": password,
        "secret": secret,
    }



