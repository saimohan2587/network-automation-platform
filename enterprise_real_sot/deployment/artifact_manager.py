"""
Purpose   : Manages persistent timestamped artifact directories (`artifacts/pre_deployment/`), saving generated `.cfg` files,
            summary reports, the manifest.json deployment contract (device identity + SHA-256 hashes + batch hash), and
            (Phase 4) the deployment_result.json controlled-deployment execution record.
Called By : main.py (`DeploymentOrchestrator.run()`, `_run_from_artifact()`), deployment/cli.py (`--use-artifact-dir` verification path).
Calls Next: Writes `.cfg`, `summary.txt`, `manifest.json`, and `deployment_result.json` to local file system.
"""

import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from deployment.logger import get_logger

logger = get_logger("ArtifactManager")

# Project root path (enterprise_real_sot directory)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"


def generate_batch_name(
    selection_criteria: Optional[Mapping[str, Any]] = None,
    devices: Optional[Sequence[Any]] = None,
) -> str:
    """
    Derives the batch name according to pipeline naming conventions:
    - Single device -> Device name (e.g. sw-access-01)
    - Multiple devices -> batch-<count> (e.g. batch-100)
    - Site deployment -> Site name if available (e.g. hyderabad)
    """
    selection_criteria = selection_criteria or {}
    devices = devices or []

    # Rule 1: Single device name passed in selection criteria
    device_name = selection_criteria.get("name")
    if device_name and isinstance(device_name, str):
        return device_name.strip()

    # Rule 2: Site name passed in selection criteria
    site_name = selection_criteria.get("site")
    if site_name and isinstance(site_name, str):
        return site_name.strip()

    # Rule 3: Evaluated device collection size
    if len(devices) == 1:
        dev = devices[0]
        if isinstance(dev, Mapping):
            return str(dev.get("name", "device-1")).strip()
        return str(getattr(dev, "name", "device-1")).strip()
    elif len(devices) > 1:
        return f"batch-{len(devices)}"

    # Check if raw devices list was passed in criteria dictionary
    devices_criteria = selection_criteria.get("devices")
    if isinstance(devices_criteria, (list, tuple)):
        if len(devices_criteria) == 1:
            return str(devices_criteria[0]).strip()
        elif len(devices_criteria) > 1:
            return f"batch-{len(devices_criteria)}"

    # Default fallback for single-device target
    return "batch-1"


def create_pre_deployment_dir(
    selection_criteria: Optional[Mapping[str, Any]] = None,
    devices: Optional[Sequence[Any]] = None,
    timestamp: Optional[datetime] = None,
    artifacts_base_dir: Optional[Path] = None,
) -> Path:
    """
    Creates and returns a new independent pre-deployment artifact directory path:
    artifacts/pre_deployment/<timestamp>_<batch_name>/

    Timestamp format: YYYYMMDD_HHMMSS
    Guarantees previous artifact folders are never overwritten or deleted.
    """
    if timestamp is None:
        timestamp = datetime.now()

    # Format timestamp as YYYYMMDD_HHMMSS
    formatted_timestamp = timestamp.strftime("%Y%m%d_%H%M%S")
    
    # Derive batch name
    batch_name = generate_batch_name(selection_criteria=selection_criteria, devices=devices)
    folder_name = f"{formatted_timestamp}_{batch_name}"

    # Target directory path
    base_dir = Path(artifacts_base_dir) if artifacts_base_dir else DEFAULT_ARTIFACTS_DIR
    target_dir = base_dir / "pre_deployment" / folder_name

    # Collision guard: Ensure sub-second repeated executions create distinct directories
    if target_dir.exists():
        counter = 1
        while (base_dir / "pre_deployment" / f"{folder_name}_{counter}").exists():
            counter += 1
        target_dir = base_dir / "pre_deployment" / f"{folder_name}_{counter}"

    # Create the directory tree on disk
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def write_summary_report(
    artifact_dir: Path,
    timestamp_str: str,
    batch_name: str,
    total_devices: int,
    assessment_passed: int,
    assessment_failed: int,
    deployment_candidates_count: int,
    skipped_devices_count: int,
    assessment_results: Sequence[Any],
) -> Path:
    """
    Generates a human-readable summary.txt file inside the artifact folder.
    Excludes CLI configurations.
    """
    summary_path = Path(artifact_dir) / "summary.txt"
    lines = [
        "================================================================================",
        "                    PRE-DEPLOYMENT ASSESSMENT BATCH SUMMARY                      ",
        "================================================================================",
        f"Timestamp            : {timestamp_str}",
        f"Batch Name           : {batch_name}",
        f"Total Devices        : {total_devices}",
        f"Assessment Passed    : {assessment_passed}",
        f"Assessment Failed    : {assessment_failed}",
        f"Deployment Candidates: {deployment_candidates_count}",
        f"Skipped Devices      : {skipped_devices_count}",
        "================================================================================",
        "",
        "--------------------------------------------------------------------------------",
        "DEVICE ASSESSMENT BREAKDOWN",
        "--------------------------------------------------------------------------------",
    ]

    for result in assessment_results:
        device_name = getattr(result, "device_name", None) or (
            result.get("name") if isinstance(result, dict) else "Unknown"
        )
        is_candidate = getattr(result, "is_candidate", False)
        failure_reason = getattr(result, "failure_reason", None)

        if is_candidate:
            lines.append(f"{device_name} PASS")
        else:
            lines.append(f"{device_name} SKIPPED")
            lines.append(f"Reason: {failure_reason or 'Pre-deployment assessment failed'}")

    lines.append("================================================================================")

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return summary_path


MANIFEST_SCHEMA_VERSION = "1.0"


def _sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file's contents, streaming to avoid loading large files whole."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _git_commit_sha() -> Optional[str]:
    """
    Resolve the git commit SHA that produced this artifact.

    Preferred order:
      1. GITHUB_SHA -- set automatically by GitHub Actions to the exact commit
         that triggered the workflow. Preferred inside CI because a runner's
         local checkout may be a shallow clone or a detached merge commit.
      2. `git rev-parse HEAD` -- local checkout fallback for manual/dev runs.

    Returns None (never a fabricated SHA) when neither source is available,
    e.g. a shallow/non-git source tree. Callers must handle None explicitly.
    """
    github_sha = os.environ.get("GITHUB_SHA")
    if github_sha:
        return github_sha.strip()

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def write_manifest(
    artifact_dir: Path,
    batch_id: str,
    timestamp: datetime,
    candidates: Sequence[Any],
    skipped: Sequence[Any],
) -> Path:
    """
    Writes manifest.json — the immutable deployment contract for this artifact.

    Only devices that passed Pre-Deployment Validation (`candidates`, whose `.cfg` files
    were already written to `artifact_dir` by the caller) are listed under `devices` and
    are eligible for deployment. Devices that failed assessment (`skipped`) are recorded
    under `excluded_devices` for audit only -- they never get a `.cfg` file, a hash, or
    a place in the deployable set. If no device passed validation, `deployable` is False
    and Phase 2 deployment must hard-refuse the whole artifact.
    """
    artifact_dir = Path(artifact_dir)

    devices = []
    for candidate in candidates:
        device_name = getattr(candidate, "device_name", None)
        device = getattr(candidate, "device", None)
        device_id = device.get("id") if isinstance(device, Mapping) else None
        device_last_updated = device.get("last_updated") if isinstance(device, Mapping) else None

        config_file = f"{device_name}.cfg"
        cfg_path = artifact_dir / config_file
        config_sha256 = _sha256_file(cfg_path) if cfg_path.exists() else None

        devices.append({
            "device_id": device_id,
            "device_name": device_name,
            "device_last_updated": device_last_updated,
            "config_file": config_file,
            "config_sha256": config_sha256,
        })

    excluded_devices = []
    for skip in skipped:
        skip_device = getattr(skip, "device", None)
        excluded_devices.append({
            "device_id": skip_device.get("id") if isinstance(skip_device, Mapping) else None,
            "device_name": getattr(skip, "device_name", None) or "unknown",
            "reason": getattr(skip, "failure_reason", None) or "Pre-deployment assessment failed",
        })

    git_commit_sha = _git_commit_sha()
    if git_commit_sha is None:
        logger.warning(
            "Git commit SHA unavailable for batch '%s' (no GITHUB_SHA env var and no git "
            "checkout detected). manifest.json will record git_commit_sha=null; this artifact "
            "cannot be traced back to a source commit.",
            batch_id,
        )

    # batch_hash covers only the deployable set, sorted by device_name for determinism.
    hasher = hashlib.sha256()
    for d in sorted(devices, key=lambda x: x["device_name"] or ""):
        hasher.update(f"{d['device_name']}:{d['config_sha256']}".encode("utf-8"))
    batch_hash = hasher.hexdigest() if devices else None

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "batch_id": batch_id,
        "created_at": timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
        "git_commit_sha": git_commit_sha,
        "deployable": len(devices) > 0,
        "devices": devices,
        "excluded_devices": excluded_devices,
        "batch_hash": batch_hash,
    }

    manifest_path = artifact_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    return manifest_path


def verify_manifest(artifact_dir: Path) -> Dict[str, Any]:
    """
    Independently re-verifies manifest.json against the `.cfg` files actually present in
    `artifact_dir`: schema version, deployable flag, a fresh SHA-256 recompute per device,
    and a fresh batch_hash recompute over those same recomputed (not manifest-recorded)
    hashes. Never trusts the hashes recorded in the manifest without recomputing them --
    this also catches a manifest that was hand-edited to match a tampered config file.

    Returns {"valid": bool, "errors": [str, ...], "manifest": dict|None}.
    Deployment from a verified artifact is a Phase 1 concern; this function only proves
    (or disproves) that the artifact is intact and eligible -- it does not deploy anything.
    """
    artifact_dir = Path(artifact_dir)
    manifest_path = artifact_dir / "manifest.json"
    errors = []

    if not manifest_path.exists():
        return {"valid": False, "errors": ["manifest.json not found in artifact directory."], "manifest": None}

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as error:
        return {"valid": False, "errors": [f"manifest.json is not valid JSON: {error}"], "manifest": None}

    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append(f"Unsupported manifest schema_version: {manifest.get('schema_version')!r}")

    if not manifest.get("deployable", False):
        errors.append("Artifact is marked deployable=false (no devices passed pre-deployment validation).")

    recomputed_hashes = []
    for device in manifest.get("devices", []):
        device_name = device.get("device_name")
        config_file = device.get("config_file")
        expected_hash = device.get("config_sha256")
        cfg_path = artifact_dir / config_file if config_file else None

        if not cfg_path or not cfg_path.exists():
            errors.append(f"Missing config file for device '{device_name}': {config_file}")
            recomputed_hashes.append((device_name, None))
            continue

        actual_hash = _sha256_file(cfg_path)
        recomputed_hashes.append((device_name, actual_hash))
        if actual_hash != expected_hash:
            errors.append(
                f"Hash mismatch for device '{device_name}' ({config_file}): "
                f"manifest={expected_hash} actual={actual_hash}"
            )

    # Recompute batch_hash from freshly-hashed files (not the manifest's own per-device
    # hashes) so a manifest tampered to match a bad file still fails this check.
    hasher = hashlib.sha256()
    for device_name, actual_hash in sorted(recomputed_hashes, key=lambda x: x[0] or ""):
        hasher.update(f"{device_name}:{actual_hash}".encode("utf-8"))
    recomputed_batch_hash = hasher.hexdigest() if recomputed_hashes else None

    if recomputed_batch_hash != manifest.get("batch_hash"):
        errors.append(
            f"Batch hash mismatch: manifest={manifest.get('batch_hash')!r} "
            f"recomputed={recomputed_batch_hash!r}"
        )

    return {"valid": len(errors) == 0, "errors": errors, "manifest": manifest}


def write_deployment_result(artifact_dir: Path, summary: Any) -> Path:
    """
    Writes deployment_result.json -- the Phase 4 controlled-deployment execution
    record for this artifact -- into the SAME artifact directory that was
    deployed, alongside manifest.json/summary.txt, so a downloaded artifact is
    self-describing after a real `--use-artifact-dir` run.

    Records, per device, `deployment_status` (did the SSH config push succeed)
    and `verification_status` (the exact post_deployment_validation verdict:
    COMPLIANT/DRIFT/UNREACHABLE/FAILED, or a deployment-layer status like
    SKIPPED/NOT_REQUIRED when verification did not run for that device) side
    by side, verbatim -- this function never collapses or renames either one.

    `summary` is a `deployment.main.DeploymentSummary` (accepted structurally,
    not by import, to avoid a circular import between this module and main.py).
    """
    artifact_dir = Path(artifact_dir)

    results = []
    for result in summary.results:
        results.append({
            "device_name": result.device_name,
            "ip_address": result.ip_address,
            "connection_status": result.connection_status,
            "deployment_status": result.deployment_status,
            "verification_status": result.verification_status,
            "state": result.state,
            "commands_sent": result.commands_sent,
            "backup_saved": result.backup_saved,
            "rollback_status": result.rollback_status,
            "error_message": result.error_message,
            "approved_by": result.approved_by,
            "approval_ref": result.approval_ref,
        })

    payload = {
        "selected_device_count": summary.selected_device_count,
        "succeeded_device_count": summary.succeeded_device_count,
        "failed_device_count": summary.failed_device_count,
        "results": results,
    }

    result_path = artifact_dir / "deployment_result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    return result_path
