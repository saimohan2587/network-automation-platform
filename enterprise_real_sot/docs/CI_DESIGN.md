# Continuous Integration (CI) Architecture & Validation Framework

## 1. Executive Summary & Architectural Boundaries

This document serves as the **Single Source of Truth** for the Continuous Integration (CI) framework of the **Network Automation Platform (N/W AP)**.

The CI pipeline serves a single, dedicated purpose: **automating static code quality, module import integrity, and declarative Source of Truth (SoT) validation on every commit and Pull Request before merging into `main`.**

> **CRITICAL ARCHITECTURAL BOUNDARY**:
> CI is strictly **STATIC** and **SAFE**. It **never** connects to live network devices (SSH/NETCONF), **never** contacts NetBox API endpoints, and **never** triggers configuration deployment actions. Network orchestration (Pre-Validation ➔ Dry-Run ➔ Approval ➔ Deployment ➔ Post-Validation) is handled exclusively by the CD / NAC Orchestration Engine.

---

## 2. Four-Layer Static Validation Framework

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
 │ AST-based static scan of internal imports & missing symbols.│
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
 └─────────────────────────────────────────────────────────────┘
```

### Layer Details:
1. **Layer 1 (Python Syntax)**: Recurses through all Python source files using `py_compile` to catch syntax and compilation errors.
2. **Layer 2 (Import Integrity)**: Statically parses Abstract Syntax Trees (`ast`) to verify that all cross-module imports and imported functions/classes exist.
3. **Layer 3 (CSV SoT Validation)**: Scans all CSV files under `csv/` for syntax readability, required headers, non-empty mandatory fields, and uniqueness constraints (`devices.csv`, `interfaces.csv`, `ip_addresses.csv`, `vlans.csv`, `prefixes.csv`).
4. **Layer 4 (YAML Config Validation)**: Validates migration and discovery manifests (`config/migration/`) for YAML parsing structure and required device pair schemas.

---

## 3. Local CI Execution Engine

To ensure developers can test changes locally before opening Pull Requests:
* **Local Entrypoint**: `python3 tests/ci_runner.py`
* **Zero Overhead**: Built using standard Python libraries (`ast`, `py_compile`, `csv`, `importlib`) and standard `PyYAML`.
* **Exit Codes**: Returns exit code `0` on 100% success across all 4 layers, and non-zero (`1`) on any validation failure.

---

## 4. Phase 3: GitHub Actions Automated Platform Integration

Phase 3 connects the local CI runner directly into GitHub's automated workflow engine.

### Workflow Configuration
* **Workflow File**: `.github/workflows/ci-validation.yml`
* **Workflow Name**: `CI Validation Pipeline`
* **Trigger Events**:
  - `push` to branch `main`
  - `pull_request` targeting branch `main`

### Execution Flow in GitHub Actions
```text
Developer pushes branch / opens PR
       │
       ▼
GitHub Actions runner provisions `ubuntu-latest`
       │
       ▼
Actions checkout repository code (`actions/checkout@v4`)
       │
       ▼
Setup Python 3.10 environment (`actions/setup-python@v5`)
       │
       ▼
Install minimal dependencies (`pip install pyyaml`)
       │
       ▼
Execute master runner: `python3 tests/ci_runner.py`
       │
  ┌────┴────┐
  ▼         ▼
[PASS]    [FAIL]
Exit 0   Exit 1 (Blocks Merge)
```

### Pull Request Quality Gate
All Pull Requests merged into `main` must pass the GitHub Actions `ci-validation` workflow automatically. If any layer fails, GitHub blocks the merge until the developer resolves the error and pushes a clean commit.

---

## 5. Verification & Safety Guarantees

* **Zero Hardware Requirements**: CI runs entirely within GitHub cloud runners without requiring GNS3 lab or hardware device access.
* **Zero Credential Requirements**: CI requires no API tokens, secrets, or SSH passwords.
* **Deterministic Results**: Running `python3 tests/ci_runner.py` locally produces identical validation results to GitHub Actions.
