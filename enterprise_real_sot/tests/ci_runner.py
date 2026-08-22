#!/usr/bin/env python3
"""
Network Automation Platform (N/W AP) - Phase 2 CI Validation Runner
-------------------------------------------------------------------
Performs automated static code quality, syntax compilation, module import
integrity, CSV Source of Truth (SoT), and YAML migration configuration checks.

Does NOT connect to NetBox, GNS3, or physical/virtual network devices.
"""

import os
import sys
import ast
import csv
import py_compile
import importlib
import importlib.util

try:
    import yaml
except ImportError:
    yaml = None

# Ensure current working directory is in Python path for module resolution
PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Directories to exclude from automated inspection
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "ENV",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".cache",
    ".vscode",
    ".idea",
    "scratch",
    "build",
    "dist"
}

# Known internal project package names for static AST import tracking
INTERNAL_PACKAGES = {
    "deployment",
    "device_migration",
    "python",
    "pre_deployment_validation",
    "post_deployment_validation",
    "src",
    "config"
}

# Expected schema constraints for key SoT CSV files
EXPECTED_CSV_SCHEMAS = {
    "csv/dcim/devices.csv": {
        "required_headers": ["name", "device_role", "device_type", "site"],
        "mandatory_fields": ["name", "device_role", "device_type", "site"],
        "unique_key": lambda row: row["name"].strip() if row.get("name") else None,
        "unique_key_name": "device name"
    },
    "csv/dcim/interfaces.csv": {
        "required_headers": ["device", "name", "type"],
        "mandatory_fields": ["device", "name", "type"],
        "unique_key": lambda row: (row["device"].strip(), row["name"].strip()) if row.get("device") and row.get("name") else None,
        "unique_key_name": "(device, interface_name)"
    },
    "csv/ipam/ip_addresses.csv": {
        "required_headers": ["address", "device", "interface"],
        "mandatory_fields": ["address", "device", "interface"],
        "unique_key": lambda row: row["address"].strip() if row.get("address") else None,
        "unique_key_name": "IP address"
    },
    "csv/ipam/vlans.csv": {
        "required_headers": ["vid", "name"],
        "mandatory_fields": ["vid", "name"],
        "unique_key": lambda row: (row.get("site", "").strip(), row["vid"].strip()) if row.get("vid") else None,
        "unique_key_name": "(site, vid)"
    },
    "csv/ipam/prefixes.csv": {
        "required_headers": ["prefix"],
        "mandatory_fields": ["prefix"],
        "unique_key": lambda row: row["prefix"].strip() if row.get("prefix") else None,
        "unique_key_name": "IP prefix"
    }
}


def run_syntax_checks(root_dir="."):
    """
    Layer 1: Recursively scans the project directory for Python files
    and verifies that each compiles cleanly without syntax errors.
    """
    print("=================================================================")
    print("      NETWORK AUTOMATION PLATFORM (N/W AP) - CI RUNNER          ")
    print("=================================================================")
    print("Task: Layer 1 - Python Syntax & Compilation Verification\n")

    passed_files = 0
    failed_files = 0
    errors = []

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, root_dir)

                try:
                    py_compile.compile(file_path, doraise=True)
                    print(f"  [PASS] {rel_path}")
                    passed_files += 1
                except py_compile.PyCompileError as e:
                    print(f"  [FAIL] {rel_path}")
                    print(f"         Error: {e.msg}")
                    failed_files += 1
                    errors.append((rel_path, e.msg))

    print("\n-----------------------------------------------------------------")
    print(f"Syntax Check Summary: {passed_files} Passed | {failed_files} Failed")
    print("-----------------------------------------------------------------")

    if failed_files > 0:
        print("\n[CI RESULT: FAILED] Syntax errors detected in the following file(s):")
        for f, msg in errors:
            print(f"  - {f}: {msg}")
        return False

    print("\n[CI RESULT: PASSED] Layer 1 Syntax check completed successfully.")
    return True


def run_import_integrity_checks(root_dir="."):
    """
    Layer 2: Statically inspects AST trees of Python files to verify
    that all internal module imports and imported symbols exist and resolve.
    """
    print("\n=================================================================")
    print("Task: Layer 2 - Python Module Import Integrity Verification\n")

    checked_imports = 0
    passed_imports = 0
    failed_imports = 0
    failures = []

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, root_dir)

                with open(file_path, "r", encoding="utf-8") as f:
                    try:
                        tree = ast.parse(f.read(), filename=file_path)
                    except Exception:
                        continue

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            top_pkg = alias.name.split(".")[0]
                            if top_pkg in INTERNAL_PACKAGES:
                                checked_imports += 1
                                try:
                                    importlib.import_module(alias.name)
                                    passed_imports += 1
                                except Exception as e:
                                    failed_imports += 1
                                    err_msg = f"{rel_path}:{node.lineno} -> import {alias.name} failed ({e})"
                                    print(f"  [FAIL] {err_msg}")
                                    failures.append(err_msg)

                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            top_pkg = node.module.split(".")[0]
                            if top_pkg in INTERNAL_PACKAGES:
                                checked_imports += 1
                                try:
                                    mod = importlib.import_module(node.module)
                                    for alias in node.names:
                                        if alias.name != "*":
                                            if hasattr(mod, alias.name):
                                                passed_imports += 1
                                            else:
                                                spec = importlib.util.find_spec(f"{node.module}.{alias.name}")
                                                if spec:
                                                    passed_imports += 1
                                                else:
                                                    failed_imports += 1
                                                    err_msg = f"{rel_path}:{node.lineno} -> from {node.module} import {alias.name} (Symbol missing)"
                                                    print(f"  [FAIL] {err_msg}")
                                                    failures.append(err_msg)
                                        else:
                                            passed_imports += 1
                                except Exception as e:
                                    failed_imports += 1
                                    err_msg = f"{rel_path}:{node.lineno} -> from {node.module} import ... failed ({e})"
                                    print(f"  [FAIL] {err_msg}")
                                    failures.append(err_msg)

    print("\n-----------------------------------------------------------------")
    print(f"Import Integrity Summary: {checked_imports} Imports Checked | {passed_imports} Passed | {failed_imports} Failed")
    print("-----------------------------------------------------------------")

    if failed_imports > 0:
        print("\n[CI RESULT: FAILED] Broken internal imports detected:")
        for fail in failures:
            print(f"  - {fail}")
        return False

    print("\n[CI RESULT: PASSED] Layer 2 Module import integrity check completed successfully.")
    return True


def run_csv_sot_checks(root_dir="."):
    """
    Layer 3: Validates declarative CSV Source of Truth files for parsing structure,
    required headers, mandatory fields, and uniqueness rules.
    """
    print("\n=================================================================")
    print("Task: Layer 3 - CSV Source of Truth (SoT) Validation\n")

    csv_dir = os.path.join(root_dir, "csv")
    if not os.path.exists(csv_dir):
        print("  [WARN] 'csv/' directory not found. Skipping Layer 3.")
        return True

    checked_files = 0
    checked_records = 0
    passed_checks = 0
    failed_checks = 0
    failures = []

    for root, dirs, files in os.walk(csv_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for file in files:
            if file.endswith(".csv"):
                file_path = os.path.join(root, file)
                rel_path = os.path.normpath(os.path.relpath(file_path, root_dir))
                checked_files += 1

                schema = EXPECTED_CSV_SCHEMAS.get(rel_path)
                seen_keys = set()
                file_ok = True

                try:
                    with open(file_path, "r", encoding="utf-8-sig") as f:
                        reader = csv.DictReader(f)
                        if not reader.fieldnames:
                            failed_checks += 1
                            file_ok = False
                            err_msg = f"{rel_path}: Empty header"
                            print(f"  [FAIL] {err_msg}")
                            failures.append(err_msg)
                            continue

                        headers = set(reader.fieldnames)
                        if schema:
                            missing_req = [h for h in schema["required_headers"] if h not in headers]
                            if missing_req:
                                failed_checks += 1
                                file_ok = False
                                err_msg = f"{rel_path}: Missing required header(s) {missing_req}"
                                print(f"  [FAIL] {err_msg}")
                                failures.append(err_msg)
                                continue

                        for line_num, row in enumerate(reader, start=2):
                            checked_records += 1
                            if schema:
                                for mand in schema["mandatory_fields"]:
                                    val = row.get(mand)
                                    if not val or not val.strip():
                                        failed_checks += 1
                                        file_ok = False
                                        err_msg = f"{rel_path}:{line_num}: Mandatory field '{mand}' is empty"
                                        print(f"  [FAIL] {err_msg}")
                                        failures.append(err_msg)

                                key = schema["unique_key"](row)
                                if key is not None:
                                    if key in seen_keys:
                                        failed_checks += 1
                                        file_ok = False
                                        err_msg = f"{rel_path}:{line_num}: Duplicate {schema['unique_key_name']} detected: '{key}'"
                                        print(f"  [FAIL] {err_msg}")
                                        failures.append(err_msg)
                                    else:
                                        seen_keys.add(key)
                                        passed_checks += 1
                            else:
                                passed_checks += 1

                except Exception as e:
                    failed_checks += 1
                    file_ok = False
                    err_msg = f"{rel_path}: Unparseable CSV syntax ({e})"
                    print(f"  [FAIL] {err_msg}")
                    failures.append(err_msg)

                if file_ok:
                    print(f"  [PASS] {rel_path}")

    print("\n-----------------------------------------------------------------")
    print(f"CSV SoT Summary: {checked_files} CSV Files Checked | {checked_records} Records Scanned | {failed_checks} Failed")
    print("-----------------------------------------------------------------")

    if failed_checks > 0:
        print("\n[CI RESULT: FAILED] CSV Source of Truth errors detected:")
        for fail in failures:
            print(f"  - {fail}")
        return False

    print("\n[CI RESULT: PASSED] Layer 3 CSV Source of Truth validation completed successfully.")
    return True


def run_yaml_config_checks(root_dir="."):
    """
    Layer 4: Validates YAML migration and discovery configuration files
    for valid syntax, non-empty structures, and mandatory manifest schemas.
    """
    print("\n=================================================================")
    print("Task: Layer 4 - YAML Migration & Discovery Config Validation\n")

    if yaml is None:
        print("  [FAIL] PyYAML module is not installed.")
        return False

    checked_files = 0
    passed_files = 0
    failed_files = 0
    failures = []

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for file in files:
            if file.endswith(".yaml") or file.endswith(".yml"):
                file_path = os.path.join(root, file)
                rel_path = os.path.normpath(os.path.relpath(file_path, root_dir))
                checked_files += 1

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)

                    if not isinstance(data, dict):
                        failed_files += 1
                        err_msg = f"{rel_path}: Top-level content must be a valid mapping dictionary"
                        print(f"  [FAIL] {err_msg}")
                        failures.append(err_msg)
                        continue

                    # Validate metadata requirement if present
                    if "metadata" in data:
                        meta = data["metadata"]
                        if not isinstance(meta, dict):
                            failed_files += 1
                            err_msg = f"{rel_path}: 'metadata' section must be a dictionary"
                            print(f"  [FAIL] {err_msg}")
                            failures.append(err_msg)
                            continue

                    # Validate migration_pairs structure if present
                    if "migration_pairs" in data:
                        pairs = data["migration_pairs"]
                        if not isinstance(pairs, list) or len(pairs) == 0:
                            failed_files += 1
                            err_msg = f"{rel_path}: 'migration_pairs' must be a non-empty list"
                            print(f"  [FAIL] {err_msg}")
                            failures.append(err_msg)
                            continue

                        pair_error = False
                        for idx, p in enumerate(pairs, start=1):
                            if not isinstance(p, dict) or not p.get("source_device") or not p.get("target_device"):
                                failed_files += 1
                                pair_error = True
                                err_msg = f"{rel_path}: migration_pair #{idx} missing required 'source_device' or 'target_device'"
                                print(f"  [FAIL] {err_msg}")
                                failures.append(err_msg)
                                break
                        if pair_error:
                            continue

                    # Validate staging_devices structure if present
                    if "staging_devices" in data:
                        devices = data["staging_devices"]
                        if not isinstance(devices, list) or len(devices) == 0:
                            failed_files += 1
                            err_msg = f"{rel_path}: 'staging_devices' must be a non-empty list"
                            print(f"  [FAIL] {err_msg}")
                            failures.append(err_msg)
                            continue

                    print(f"  [PASS] {rel_path}")
                    passed_files += 1

                except yaml.YAMLError as e:
                    failed_files += 1
                    err_msg = f"{rel_path}: Invalid YAML syntax ({e})"
                    print(f"  [FAIL] {err_msg}")
                    failures.append(err_msg)

    print("\n-----------------------------------------------------------------")
    print(f"YAML Config Summary: {checked_files} YAML Files Checked | {passed_files} Passed | {failed_files} Failed")
    print("-----------------------------------------------------------------")

    if failed_files > 0:
        print("\n[CI RESULT: FAILED] YAML configuration errors detected:")
        for fail in failures:
            print(f"  - {fail}")
        return False

    print("\n[CI RESULT: PASSED] Layer 4 YAML Migration Config validation completed successfully.")
    return True


def run_capability_resolver_tests():
    """
    Layer 5: Capability Resolver Unit Tests.
    Verifies that protocol capability gate accurately allows/skips plugins based on device role.
    """
    print("\n=================================================================")
    print("Task: Layer 5 - Protocol Capability Gate & Applicability Tests\n")

    from deployment.capability_resolver import CapabilityResolver
    from deployment.protocols.stp import StpProtocol
    from deployment.protocols.ntp import NtpProtocol
    from deployment.protocols.cdp import CdpProtocol
    from deployment.protocols.dns import DnsProtocol
    from deployment.protocols.syslog import SyslogProtocol
    from deployment.protocols.snmp import SnmpProtocol


    stp = StpProtocol()
    ntp = NtpProtocol()
    cdp = CdpProtocol()
    dns = DnsProtocol()
    syslog = SyslogProtocol()
    snmp = SnmpProtocol()

    tests = [
        # TEST 1: Router context contains STP configuration -> Skipped
        {
            "name": "TEST 1: Router context contains STP config -> STP skipped",
            "plugin": stp,
            "context": {"device_info": {"role": "l3-gateway-router"}, "config": {"stp": {"mode": "rapid-pvst"}}},
            "expected_supported": False,
        },
        # TEST 2: Access switch context contains STP configuration -> Allowed
        {
            "name": "TEST 2: Access switch context contains STP config -> STP allowed",
            "plugin": stp,
            "context": {"device_info": {"role": "access-switch"}, "config": {"stp": {"mode": "rapid-pvst"}}},
            "expected_supported": True,
        },
        # TEST 3: Unknown role contains STP configuration -> Skipped using safe baseline
        {
            "name": "TEST 3: Unknown role contains STP config -> STP skipped",
            "plugin": stp,
            "context": {"device_info": {"role": "unknown-device-role-123"}, "config": {"stp": {"mode": "rapid-pvst"}}},
            "expected_supported": False,
        },
        # TEST 4: Router context contains NTP configuration -> Allowed
        {
            "name": "TEST 4: Router context contains NTP config -> NTP allowed",
            "plugin": ntp,
            "context": {"device_info": {"role": "l3-gateway-router"}, "config": {"ntp": {"servers": ["10.0.0.1"]}}},
            "expected_supported": True,
        },
        # TEST 5: Router context contains CDP configuration -> Allowed
        {
            "name": "TEST 5: Router context contains CDP config -> CDP allowed",
            "plugin": cdp,
            "context": {"device_info": {"role": "l3-gateway-router"}, "config": {"cdp": {"enabled": True}}},
            "expected_supported": True,
        },
        # TEST 6: Router context contains DNS configuration -> Allowed
        {
            "name": "TEST 6: Router context contains DNS config -> DNS allowed",
            "plugin": dns,
            "context": {"device_info": {"role": "l3-gateway-router"}, "config": {"dns": {"domain_name": "lab.internal"}}},
            "expected_supported": True,
        },
        # TEST 7: Router context contains Syslog configuration -> Allowed
        {
            "name": "TEST 7: Router context contains Syslog config -> Syslog allowed",
            "plugin": syslog,
            "context": {"device_info": {"role": "l3-gateway-router"}, "config": {"syslog": {"servers": ["10.0.0.50"]}}},
            "expected_supported": True,
        },
        # TEST 8: Router context contains SNMP configuration -> Allowed
        {
            "name": "TEST 8: Router context contains SNMP config -> SNMP allowed",
            "plugin": snmp,
            "context": {"device_info": {"role": "l3-gateway-router"}, "config": {"snmp": {"location": "Lab"}}},
            "expected_supported": True,
        },
    ]


    passed = 0
    failed = 0

    for test in tests:
        res = CapabilityResolver.is_supported(test["plugin"], test["context"])
        if res == test["expected_supported"]:
            print(f"  [PASS] {test['name']}")
            passed += 1
        else:
            print(f"  [FAIL] {test['name']} (Got: {res}, Expected: {test['expected_supported']})")
            failed += 1

    print("\n-----------------------------------------------------------------")
    print(f"Capability Gate Summary: {passed} Passed | {failed} Failed")
    print("-----------------------------------------------------------------")

    if failed > 0:
        print("\n[CI RESULT: FAILED] Capability gate unit tests failed.")
        return False

    print("\n[CI RESULT: PASSED] Layer 5 Capability Gate unit tests completed successfully.")
    return True


def run_phase43_orchestration_tests():
    """
    Layer 6: Phase 4.3 CD Pipeline Integration & Orchestration Tests.
    Tests Change Planning, Idempotency, Pre-Change Backup, Selective Deployment, Rollback, and Verification.
    """
    print("\n=================================================================")
    print("Task: Layer 6 - Phase 4.3 CD Selective Deployment & Rollback Tests\n")

    from deployment.device_connector import DeviceConnector, DeploymentResult
    from deployment.lifecycle import DeviceLifecycleState

    class MockConnection:
        def __init__(self, running_config="", fail_config=False):
            self.running_config = running_config
            self.fail_config = fail_config
            self.sent_config_sets = []

        def send_command(self, cmd, read_timeout=30):
            if "show running-config" in cmd:
                return self.running_config
            if "logging" in cmd:
                return "Logging to 10.10.10.50"
            if "snmp" in cmd:
                return "snmp-server community NOC-ReadOnly RO"
            if "domain" in cmd or "name-server" in cmd:
                return "ip domain name lab.enterprise.internal"
            return ""

        def send_config_set(self, cmds, read_timeout=120):
            self.sent_config_sets.append(cmds)
            if self.fail_config:
                return "% Invalid input detected at '^' marker."
            return "OK"

        def save_config(self, cmd=None):
            return "OK"

        def disconnect(self):
            pass

    # TEST 1: Idempotency (Fully Compliant Device)
    mock_running = "cdp run\nntp source FastEthernet0/0\nip domain name lab.enterprise.internal\nlogging host 10.10.10.50\nsnmp-server community NOC-ReadOnly RO"
    connector = DeviceConnector(connection_factory=lambda **kw: MockConnection(running_config=mock_running))
    res1 = connector.deploy("R1_gns3", {"host": "10.10.10.2"}, mock_running, save_config=True)

    test1_pass = res1.state == DeviceLifecycleState.ALREADY_COMPLIANT.value and res1.commands_sent == 0

    # TEST 2: Selective Change (1 command missing)
    gen_config_2 = "cdp run\nlogging host 10.10.10.50\nsnmp-server location GNS3-Staging-Rack1"
    connector2 = DeviceConnector(connection_factory=lambda **kw: MockConnection(running_config=mock_running))
    res2 = connector2.deploy("R1_gns3", {"host": "10.10.10.2"}, gen_config_2, save_config=True)

    test2_pass = res2.change_required_count == 1 and res2.commands_sent == 1

    # TEST 3: CLI Error & Safe Rollback
    connector3 = DeviceConnector(connection_factory=lambda **kw: MockConnection(running_config="", fail_config=True))
    res3 = connector3.deploy("R1_gns3", {"host": "10.10.10.2"}, "snmp-server location Lab", save_config=True)

    test3_pass = res3.state == DeviceLifecycleState.ROLLBACK_SUCCESSFUL.value and res3.rollback_status == "SUCCESSFUL"

    tests = [
        ("TEST 1: Fully compliant device -> 0 commands sent (ALREADY_COMPLIANT)", test1_pass),
        ("TEST 2: Selective deployment -> only missing command sent (1 command)", test2_pass),
        ("TEST 3: CLI Error detection -> triggers safe rollback (ROLLBACK_SUCCESSFUL)", test3_pass),
    ]

    passed = 0
    failed = 0
    for name, ok in tests:
        if ok:
            print(f"  [PASS] {name}")
            passed += 1
        else:
            print(f"  [FAIL] {name}")
            failed += 1

    print("\n-----------------------------------------------------------------")
    print(f"Phase 4.3 Summary: {passed} Passed | {failed} Failed")
    print("-----------------------------------------------------------------")

    if failed > 0:
        print("\n[CI RESULT: FAILED] Phase 4.3 CD pipeline unit tests failed.")
        return False

    print("\n[CI RESULT: PASSED] Layer 6 Phase 4.3 CD Pipeline tests completed successfully.")
    return True


def main():
    """Main execution entrypoint for CI runner."""
    syntax_ok = run_syntax_checks()
    if not syntax_ok:
        sys.exit(1)

    import_ok = run_import_integrity_checks()
    if not import_ok:
        sys.exit(1)

    csv_ok = run_csv_sot_checks()
    if not csv_ok:
        sys.exit(1)

    yaml_ok = run_yaml_config_checks()
    if not yaml_ok:
        sys.exit(1)

    cap_ok = run_capability_resolver_tests()
    if not cap_ok:
        sys.exit(1)

    p43_ok = run_phase43_orchestration_tests()
    if not p43_ok:
        sys.exit(1)

    print("\n=================================================================")
    print(" [SUCCESS] ALL CI VALIDATION CHECKS PASSED (LAYERS 1, 2, 3, 4, 5 & 6)")
    print("=================================================================")
    sys.exit(0)


if __name__ == "__main__":
    main()


