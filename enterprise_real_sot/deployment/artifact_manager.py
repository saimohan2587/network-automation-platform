"""
Purpose   : Manages persistent timestamped artifact directories (`artifacts/pre_deployment/`), saving generated `.cfg` files and summary reports.
Called By : main.py (`DeploymentOrchestrator.run()`).
Calls Next: Writes `.cfg` files and `summary.txt` to local file system.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence



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
