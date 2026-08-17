import os

def _load_env():
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    _load_env()

NETBOX_URL = os.getenv("NETBOX_URL", "http://localhost:8000").rstrip("/")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN", "")
CSV_DIR = os.getenv("CSV_DIR", "./csv")
