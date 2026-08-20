# Phase 2: CI Pipeline Architecture & Validation Framework

## 1. Executive Summary

This document defines the **Continuous Integration (CI)** framework for the **Network Automation Platform (N/W AP)**. 

The CI pipeline serves a single, dedicated purpose: **automating code quality and static validation of repository changes on Pull Requests before merging into `main`.**

> **CRITICAL ARCHITECTURAL BOUNDARY**:
> CI **never** connects to live network devices and **never** triggers NetBox imports or deployment actions. Live network orchestration (Pre-Validation ➔ Dry-Run ➔ Approval ➔ Deployment ➔ Post-Validation) is handled exclusively by the CD / NAC Orchestration Engine.

---

## 2. CI Pipeline Responsibilities & Verification Layers

The CI suite validates 4 core project layers:

```text
 ┌─────────────────────────────────────────────────────────────┐
 │ Layer 1: Python Syntax & Compilation Check                  │
 │ Recurses through all .py files to ensure zero syntax errors.│
 └──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ Layer 2: Python Module Import Integrity                     │
 │ Validates that core package structures import cleanly.      │
 └──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ Layer 3: Declarative CSV Source of Truth (SoT) Validation   │
 │ Validates headers, column alignment, and formatting in csv/ │
 └──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ Layer 4: Migration & Discovery YAML Config Validation       │
 │ Validates YAML syntax & structure under config/             │
 └─────────────────────────────────────────────────────────────┘
```

---

## 3. Tooling Strategy

To ensure high reliability across local developer workstations and remote CI environments:
* **Standard Library First**: Built using Python standard libraries (`py_compile`, `importlib`, `csv`, `pyyaml` / native parsers) to guarantee execution without complex dependency chains.
* **Portable Local Runner**: Local script runnable via `python3 tests/ci_runner.py` prior to pushing feature branches.
* **Pull Request Gate**: PRs must pass all 4 layers before code review and merge approval.
