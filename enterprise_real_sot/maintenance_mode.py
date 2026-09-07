#!/usr/bin/env python3
"""
Maintenance Mode / Monitoring Suppression CLI.

Thin HTTP client for the ServiceNow webhook adapter's /maintenance/* routes.
It does NOT read or write any local state file directly: the adapter runs in
a container whose servicenow/storage directory is backed by a separate Docker
volume from this host's filesystem, so the only reliable shared source of
truth is the adapter's own running process, reached over the port it already
exposes (localhost:8000 by default, matching observability/docker-compose.yml
and enterprise_real_sot/.env's WEBHOOK_PORT).

Usage:
    python3 maintenance_mode.py enable --reason "Planned GNS3 lab shutdown" --duration 8h
    python3 maintenance_mode.py enable --reason "SW2 maintenance" --duration 1h --device SW2_gns3
    python3 maintenance_mode.py status
    python3 maintenance_mode.py disable
    python3 maintenance_mode.py disable --no-grace
    python3 maintenance_mode.py grace --duration 300
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _adapter_url() -> str:
    return os.getenv("SERVICENOW_ADAPTER_URL", "http://localhost:8000").rstrip("/")


def _post(path: str, payload: dict) -> dict:
    url = f"{_adapter_url()}{path}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"ERROR: adapter rejected the request ({e.code}): {e.read().decode('utf-8')}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(
            f"ERROR: could not reach the ServiceNow adapter at {url}: {e}\n"
            "Is the observability stack running? (docker ps | grep servicenow_adapter)",
            file=sys.stderr,
        )
        sys.exit(1)


def _get(path: str) -> dict:
    url = f"{_adapter_url()}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(
            f"ERROR: could not reach the ServiceNow adapter at {url}: {e}\n"
            "Is the observability stack running? (docker ps | grep servicenow_adapter)",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_enable(args: argparse.Namespace) -> None:
    result = _post(
        "/maintenance/enable",
        {
            "reason": args.reason,
            "duration": args.duration,
            "devices": args.device or [],
            "sites": args.site or [],
        },
    )
    print(result.get("formatted", json.dumps(result, indent=2)))


def cmd_disable(args: argparse.Namespace) -> None:
    result = _post(
        "/maintenance/disable",
        {
            "apply_grace": not args.no_grace,
            "grace_seconds": args.grace,
        },
    )
    print(result.get("formatted", json.dumps(result, indent=2)))


def cmd_grace(args: argparse.Namespace) -> None:
    result = _post("/maintenance/grace", {"duration_seconds": args.duration})
    print(result.get("formatted", json.dumps(result, indent=2)))


def cmd_status(_args: argparse.Namespace) -> None:
    result = _get("/maintenance/status")
    print(result.get("formatted", json.dumps(result, indent=2)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Maintenance Mode / Monitoring Suppression control.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_enable = sub.add_parser("enable", help="Suppress ServiceNow incident creation for planned maintenance.")
    p_enable.add_argument("--reason", required=True, help="Why maintenance is being enabled (required, for visibility).")
    p_enable.add_argument("--duration", default=None, help="e.g. '8h', '30m', '1d'. Defaults to MAINTENANCE_DEFAULT_DURATION (4h) if omitted.")
    p_enable.add_argument("--device", action="append", default=None, help="Scope to one device (repeatable). Omit for global (all devices).")
    p_enable.add_argument("--site", action="append", default=None, help="Scope to one site (repeatable). Omit for global.")
    p_enable.set_defaults(func=cmd_enable)

    p_disable = sub.add_parser("disable", help="Disable maintenance mode and resume normal ServiceNow incident creation.")
    p_disable.add_argument("--no-grace", action="store_true", help="Skip the automatic startup grace period.")
    p_disable.add_argument("--grace", type=int, default=None, help="Override the startup grace period, in seconds.")
    p_disable.set_defaults(func=cmd_disable)

    p_grace = sub.add_parser("grace", help="Apply a startup grace period without touching maintenance enable/disable state.")
    p_grace.add_argument("--duration", type=int, default=None, help="Grace period in seconds. Defaults to DEVICE_STARTUP_GRACE_PERIOD (300).")
    p_grace.set_defaults(func=cmd_grace)

    p_status = sub.add_parser("status", help="Show current maintenance mode / grace period state.")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
