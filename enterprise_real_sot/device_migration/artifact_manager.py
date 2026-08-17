"""Artifact manager for device_migration package."""

import os
import json
from datetime import datetime
from typing import Dict, Any, List

from device_migration.logger import get_logger

logger = get_logger("ArtifactManager")


class MigrationArtifactManager:
    """Manages output directory structure and exports JSON artifacts."""

    def __init__(self, batch_name: str, base_dir: str = "artifacts/migration"):
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)
        logger.info("Initialized migration artifact base directory: '%s'", self.base_dir)

    def export_pair_artifacts(
        self,
        source_device: str,
        target_device: str,
        migration_dataset: Dict[str, Any],
        interface_mapping: List[Dict[str, Any]],
        raw_outputs: Dict[str, str]
    ) -> str:
        """Export per-pair migration_dataset.json, interface_mapping.json, and raw_outputs.json."""
        pair_dir = os.path.join(self.base_dir, f"{source_device}_to_{target_device}")
        os.makedirs(pair_dir, exist_ok=True)

        dataset_path = os.path.join(pair_dir, "migration_dataset.json")
        with open(dataset_path, "w", encoding="utf-8") as f:
            json.dump(migration_dataset, f, indent=2)

        mapping_path = os.path.join(pair_dir, "interface_mapping.json")
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(interface_mapping, f, indent=2)

        outputs_path = os.path.join(pair_dir, "raw_outputs.json")
        with open(outputs_path, "w", encoding="utf-8") as f:
            json.dump(raw_outputs, f, indent=2)

        logger.info("Exported per-pair artifacts for '%s -> %s' into '%s'", source_device, target_device, pair_dir)
        return pair_dir

    def export_pair_failure(self, source_device: str, target_device: str, error_message: str, stack_trace: str = "") -> str:
        """Export failure report artifact if a migration pair encounters an exception."""
        pair_dir = os.path.join(self.base_dir, f"{source_device}_to_{target_device}")
        os.makedirs(pair_dir, exist_ok=True)

        failure_path = os.path.join(pair_dir, "failure_report.json")
        report = {
            "source_device": source_device,
            "target_device": target_device,
            "timestamp": datetime.now().isoformat(),
            "status": "FAILED",
            "error": error_message,
            "stack_trace": stack_trace
        }
        with open(failure_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.error("Exported failure report for '%s -> %s' into '%s'", source_device, target_device, failure_path)
        return failure_path

    def export_batch_summary(self, summary_data: Dict[str, Any]) -> str:
        """Export summary.json into pair directories and root base directory."""
        summary_paths = []
        for p in summary_data.get("pairs", []):
            if "source_device" in p and "target_device" in p:
                p_dir = os.path.join(self.base_dir, f"{p['source_device']}_to_{p['target_device']}")
                os.makedirs(p_dir, exist_ok=True)
                p_summary_path = os.path.join(p_dir, "summary.json")
                with open(p_summary_path, "w", encoding="utf-8") as f:
                    json.dump(summary_data, f, indent=2)
                summary_paths.append(p_summary_path)

        root_summary_path = os.path.join(self.base_dir, "summary.json")
        with open(root_summary_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)

        logger.info("Exported summary report into pair directory: '%s'", summary_paths)
        return root_summary_path

