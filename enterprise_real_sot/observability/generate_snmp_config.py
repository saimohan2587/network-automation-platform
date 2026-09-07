#!/usr/bin/env python3
"""
Renders observability/snmp_exporter/snmp.yml from snmp.yml.template, substituting
${SNMP_COMMUNITY} with the real value from enterprise_real_sot/.env.

Why this exists: prom/snmp-exporter is a static-config Go binary with no native
environment-variable support and no shell in its image to run an entrypoint
substitution step, so the community string previously had to be hardcoded
directly in snmp.yml. This script moves the real value to .env (like every
other credential in this project) and keeps only a placeholder template in
version control - snmp.yml itself (the rendered file, containing the real
value) is git-ignored.

Run this once before `docker-compose up`, and again any time SNMP_COMMUNITY
changes in .env (then restart the snmp_exporter container to pick it up).
"""

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOT_DIR = HERE.parent
TEMPLATE_FILE = HERE / "snmp_exporter" / "snmp.yml.template"
OUTPUT_FILE = HERE / "snmp_exporter" / "snmp.yml"
ENV_FILE = SOT_DIR / ".env"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip("'\"")
            os.environ.setdefault(key, val)


def render() -> None:
    _load_env_file(ENV_FILE)

    community = os.getenv("SNMP_COMMUNITY")
    if not community:
        print(
            "ERROR: SNMP_COMMUNITY is not set in .env - refusing to render a config "
            "with an empty community string.",
            file=sys.stderr,
        )
        sys.exit(1)

    template_text = TEMPLATE_FILE.read_text(encoding="utf-8")
    rendered = re.sub(r"\$\{SNMP_COMMUNITY\}", community, template_text)

    OUTPUT_FILE.write_text(rendered, encoding="utf-8")
    print(f"Rendered {OUTPUT_FILE} from {TEMPLATE_FILE.name} (community value not printed).")


if __name__ == "__main__":
    render()
