# Continuous Integration (CI) Architecture & Validation Framework

## 1. Executive Summary & Architectural Boundaries

This document serves as the **Single Source of Truth** for the Continuous Integration (CI) framework of the **Network Automation Platform (N/W AP)**.

The CI pipeline serves a single, dedicated purpose: **automating static code quality, module import integrity, and declarative Source of Truth (SoT) validation on every commit and Pull Request before merging into `main`.**

> **CRITICAL ARCHITECTURAL BOUNDARY**:
> CI is strictly **SAFE** and **ISOLATED**. It **never** connects to live network devices (SSH/NETCONF), **never** contacts NetBox API endpoints, and **never** triggers configuration deployment actions. Network orchestration (Pre-Validation ➔ Dry-Run ➔ Approval ➔ Deployment ➔ Post-Validation) is handled exclusively by the CD / NAC Orchestration Engine.

---

## 2. Four-Layer Validation Framework

The CI suite validates repository integrity across 4 sequential verification layers:

```text
 ┌─────────────────────────────────────────────────────────────┐
 │ Layer 1: Python Syntax & Compilation Verification           │
 │ Recurses through all .py files to ensure zero syntax errors.│
 └──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ Layer 2: Python Module Import Integrity Verification        │
 │ AST discovery + importlib runtime resolution check.         │
 └──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ Layer 3: Declarative CSV Source of Truth (SoT) Validation   │
 │ Validates headers, mandatory fields, & uniqueness in csv/   │
 └──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ Layer 4: Migration & Discovery YAML Config Validation       │
 │ Validates YAML syntax & manifest schemas under config/      │
 └──────────────────────────────┴──────────────────────────────┘
```

### Layer Specifications:
1. **Layer 1 (Python Syntax)**: Recurses through all Python source files using `py_compile` to catch syntax and compilation errors.
2. **Layer 2 (Import Integrity)**: Scans Abstract Syntax Trees (`ast`) to discover internal module imports, then verifies symbol resolution using `importlib.import_module`.
3. **Layer 3 (CSV SoT Validation)**: Scans all CSV files under `csv/` for syntax readability, required headers, non-empty mandatory fields, and uniqueness constraints (`devices.csv`, `interfaces.csv`, `ip_addresses.csv`, `vlans.csv`, `prefixes.csv`).
4. **Layer 4 (YAML Config Validation)**: Validates migration and discovery manifests (`config/migration/`) for YAML parsing structure and required device pair schemas.

---

## 3. Layer 2 Implementation Reality Check: Truly Static or Not?

### Execution Mechanism
Layer 2 uses `ast.walk` to discover internal project import statements (`deployment`, `device_migration`, `python`, etc.), but then calls `importlib.import_module(module_name)` to verify that the module and its exported symbols resolve cleanly.

### Is Layer 2 Purely Static?
* **No, Layer 2 is NOT pure static analysis** (such as AST-only traversal or external tools like `mypy` or `flake8`).
* Because `importlib.import_module` actually loads Python modules into memory, Python executes top-level module statements at import time.
* Consequently, if an imported project module depends on third-party libraries (e.g., `requests`, `netmiko`, `python-dotenv`), those packages **must be installed in the Python runtime environment**, or `importlib.import_module` will fail with `ModuleNotFoundError`.

### Why Layer 2 Remains Safe
Despite loading modules at runtime via `importlib`, Layer 2 remains **100% safe**:
* Project modules follow strict architectural standards: top-level module code only defines classes, functions, dataclasses, and constants.
* No network connections, socket bindings, SSH sessions, or NetBox API calls are executed at top-level import time.

---

## 4. Local CI Execution Engine

To ensure developers can test changes locally before opening Pull Requests:
* **Local Entrypoint**:
  ```bash
  cd enterprise_real_sot
  python3 tests/ci_runner.py
  ```
* **Dependency Requirement**: Requires all project dependencies listed in `enterprise_real_sot/requirements.txt` to be installed in the active environment.
* **Exit Codes**: Returns exit code `0` on 100% success across all 4 layers, and non-zero (`1`) on any validation failure.

---

## 5. Phase 3: GitHub Actions Automated Platform Integration

Phase 3 connects the local CI runner directly into GitHub's automated workflow engine.

### Workflow Configuration
* **Workflow File**: `.github/workflows/ci-validation.yml`
* **Workflow Name**: `CI Validation Pipeline`
* **Trigger Events**:
  - `push` to branch `main`
  - `pull_request` targeting branch `main`

### Repository Root vs. Application Directory Structure
The Git repository root is `network-automation-platform/`, while all application source code, test runners, CSV SoT data, and configuration manifests reside inside `enterprise_real_sot/`:
```text
network-automation-platform/          ← Git Repository Root
├── .github/
│   └── workflows/
│       └── ci-validation.yml
└── enterprise_real_sot/              ← Application Directory (Working Directory)
    ├── tests/
    │   └── ci_runner.py
    ├── requirements.txt              ← Dependency Source of Truth
    ├── deployment/
    ├── device_migration/
    ├── csv/
    └── config/
```
To ensure `tests/ci_runner.py` and relative file paths (`csv/`, `config/`, `requirements.txt`) resolve correctly, the GitHub Actions job explicitly sets:
```yaml
defaults:
  run:
    working-directory: enterprise_real_sot
```

### Local vs. GitHub Runner Divergence (Root Cause & Fix)

#### Root Cause Analysis
* **Local Developer Machine**: `python3 tests/ci_runner.py` succeeded locally because third-party dependencies (`requests`, `netmiko`, `python-dotenv`, `pyyaml`) were already installed in the local Python environment.
* **GitHub Actions Cloud Runner**: The fresh `ubuntu-latest` runner only had Python standard library installed. The workflow previously executed `pip install pyyaml`, missing `requests` and `netmiko`. When Layer 2 executed `importlib.import_module('deployment.netbox_client')`, Python failed with `ModuleNotFoundError: No module named 'requests'`.

#### Dependency Installation Strategy
Instead of hardcoding arbitrary `pip install` commands in the workflow, the dependency Source of Truth is centralized in `enterprise_real_sot/requirements.txt`:
```text
pyyaml>=6.0
requests>=2.28.0
netmiko>=4.1.0
python-dotenv>=1.0.0
```
The GitHub Actions workflow step installs all project dependencies cleanly via:
```yaml
- name: Install CI Dependencies
  run: |
    python -m pip install --upgrade pip
    pip install -r requirements.txt
```

### Execution Flow in GitHub Actions
```text
Developer pushes branch / opens PR
       │
       ▼
GitHub Actions provisions `ubuntu-latest` runner
       │
       ▼
Actions checkout repository code (`actions/checkout@v4`)
       │
       ▼
Setup Python 3.10 environment with pip cache (`actions/setup-python@v5`)
       │
       ▼
Install dependencies from `requirements.txt` (`pip install -r requirements.txt`)
       │
       ▼
Execute runner: `python3 tests/ci_runner.py` (CWD: `enterprise_real_sot`)
       │
  ┌────┴────┐
  ▼         ▼
[PASS]    [FAIL]
Exit 0   Exit 1 (Blocks Merge)
```

---

## 6. Verification & Safety Guarantees

* **Zero Hardware Requirements**: CI runs entirely within cloud runners without requiring GNS3 lab access or physical network devices.
* **Zero Credential Requirements**: CI requires no API tokens, secrets, or SSH passwords (`.env` remains untracked and excluded).
* **Deterministic Parity**: Installing `requirements.txt` ensures local execution (`python3 tests/ci_runner.py`) produces 100% identical validation results to GitHub Actions.
