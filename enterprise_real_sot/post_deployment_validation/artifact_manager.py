"""Artifact Manager for Post-Deployment Validation Compliance Reports."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from post_deployment_validation.logger import get_logger

logger = get_logger("PostDeploymentArtifactManager")

BASE_ARTIFACT_DIR = Path("artifacts") / "post_deployment"


class ArtifactManager:
    """Manages timestamped artifact directory creation and exports summary.json and per-device drift json files."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = base_dir or BASE_ARTIFACT_DIR

    def create_post_deployment_dir(self, batch_name: str) -> Path:
        """Create an independent timestamped directory under artifacts/post_deployment/."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sanitized_batch = self._sanitize_filename(batch_name)
        folder_name = f"{timestamp}_{sanitized_batch}"
        target_dir = self.base_dir / folder_name

        # Sub-second execution collision guard
        counter = 1
        original_dir = target_dir
        while target_dir.exists():
            target_dir = Path(f"{original_dir}_{counter}")
            counter += 1

        target_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Created post-deployment artifact directory: %s", target_dir.resolve())
        return target_dir

    def write_reports(
        self,
        artifact_dir: Path,
        summary_data: Dict[str, Any],
        device_results: List[Dict[str, Any]],
    ) -> Dict[str, Path]:
        """Write summary.json and per-device <device_name>.json containing DRIFT-only records."""
        written_files: Dict[str, Path] = {}

        # 1. Write summary.json
        json_path = artifact_dir / "summary.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)
        written_files["summary.json"] = json_path

        # 2. Write per-device <device_name>.json for drifted or failed devices (DRIFT ONLY)
        for dev in device_results:
            dev_name = dev.get("device_name", "unknown")
            dev_status = dev.get("overall_status")
            if dev_status in ("DRIFT", "FAILED"):
                # Filter out all PASS entries and build drift-only payload
                drift_payload = self._build_drift_only_device_payload(dev)
                dev_filename = f"{self._sanitize_filename(dev_name)}.json"
                dev_json_path = artifact_dir / dev_filename
                with open(dev_json_path, "w", encoding="utf-8") as f:
                    json.dump(drift_payload, f, indent=2)
                written_files[dev_filename] = dev_json_path

        return written_files

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Sanitize string for filesystem paths."""
        return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)

    @staticmethod
    def _build_drift_only_device_payload(dev: Dict[str, Any]) -> Dict[str, Any]:
        """Extract ONLY configuration drift entries, omitting all PASS and compliant items."""
        drifts: List[Dict[str, Any]] = []
        for res in dev.get("resource_results", []):
            protocol = res.get("resource_name", "")
            scope = res.get("scope_name", "")
            for field in res.get("field_results", []):
                if field.get("status") == "DRIFT":
                    drifts.append({
                        "protocol": protocol,
                        "scope": scope,
                        "field_name": field.get("field_name"),
                        "expected": field.get("expected"),
                        "actual": field.get("actual"),
                        "reason": field.get("reason") or "Configuration drift detected",
                    })

        return {
            "device_name": dev.get("device_name"),
            "ip_address": dev.get("ip_address"),
            "overall_status": dev.get("overall_status"),
            "error_message": dev.get("error_message"),
            "total_drifts": len(drifts),
            "drifts": drifts,
        }
