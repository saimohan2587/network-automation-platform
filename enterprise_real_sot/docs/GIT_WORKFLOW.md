# Network Automation Platform (N/W AP) - Git Workflow & Repository Guidelines

## 1. Executive Summary

This document defines the enterprise Git workflow for the **Network Automation Platform (N/W AP)**. It establishes clean repository hygiene, protects environment secrets, and defines how code changes move safely from local development to production approval.

---

## 2. Core Architectural Responsibilities

To maintain high software quality and operational safety, N/W AP strictly separates platform responsibilities:

| Component | Primary Responsibility | Key Tools / Standards |
| :--- | :--- | :--- |
| **Git** | Version control, change tracking, and peer review history. | Branch protection, PR reviews, commit hygiene. |
| **Python Engine** | Core platform baseline: discovery, parsing, NetBox importers, pre/post validation, compliance reports. | Native Python modules, `requests`, `pynetbox`, `netmiko`. |
| **CI (Continuous Integration)** | Automated code validation on Pull Requests before merging into `main`. | `flake8`, `pytest`, `yaml-lint`. (Code checks ONLY, no live network pushes). |
| **CD (Continuous Delivery)** | Controlled execution & orchestration of the NAC lifecycle. | Python NAC Orchestration Engine with dry-run and approval gates. |
| **Ansible** | Future execution engine for large-scale multi-device batch tasks (1,000+ nodes). | Ansible playbooks & runner (used selectively without rewriting Python code). |

---

## 3. Branching Model

N/W AP uses a simplified, enterprise-grade branching strategy based on a single long-lived branch (`main`) and short-lived feature branches (`feature/*`).

```text
  main (Production Baseline)
   │
   ├───────────► feature/add-bgp-validation ───────────┐
   │             (Local Dev & Testing)                │
   │                                                  ▼
   │                                           Pull Request (PR)
   │                                                  │
   │                                           Automated CI Checks
   │                                                  │
   │                                           Peer Code Review
   │                                                  │
   ◄──────────────────────────────────────────────────┘ (Merge)
```

### Branch Conventions:
* `main`: Protected production branch. Represents the current validated platform baseline.
* `feature/<short-description>`: All changes (new features, validator additions, parser fixes) are developed in feature branches.
  * Examples: `feature/git-foundation`, `feature/pre-validation-enhancement`, `feature/ansible-batch-runner`.

---

## 4. Developer Workflow Step-by-Step

### Step 1: Create a Feature Branch
Always start from an up-to-date `main` branch:
```bash
git checkout main
git pull origin main
git checkout -b feature/my-new-feature
```

### Step 2: Local Development & Verification
* Perform local edits and testing.
* Copy `.env.example` to `.env` for local environment credentials (never commit `.env`).
* Validate changes locally using python test scripts or dry-run modes.

### Step 3: Commit Changes
Write clear, concise commit messages detailing the business rationale:
```bash
git add .
git commit -m "feat(validation): add IPv6 prefix verification to pre-deployment suite"
```

### Step 4: Push Feature Branch & Open Pull Request
```bash
git push -u origin feature/my-new-feature
```
Open a Pull Request (PR) against `main` on GitHub/GitLab.

### Step 5: Automated CI Checks & Peer Review
* CI automatically runs syntax, formatting, and unit tests on the PR code.
* Senior Lead / Peer Engineer reviews the PR code diff.
* Once approved and CI passes, merge the PR into `main`.

---

## 5. Repository Hygiene & Secret Protection

1. **Never Commit Secrets**: Real passwords, API tokens, and private keys must remain in `.env` or secure vault systems.
2. **Environment Template**: Use `.env.example` to document required configuration parameters.
3. **Ignored Runtime Files**: Temporary logs (`*.log`), caches (`__pycache__/`, `.pytest_cache/`), editor files (`.vscode/`, `.idea/`), and python virtual environments (`.venv/`) are excluded via `.gitignore`.
4. **Declarative SoT Integrity**: CSV files under `csv/` represent declarative Source of Truth records and must be updated via structured commits.
