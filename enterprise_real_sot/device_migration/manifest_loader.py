"""Manifest loader and validator for device_migration package."""

import os
import json
import yaml
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from device_migration.logger import get_logger

logger = get_logger("ManifestLoader")


@dataclass
class PatternMapping:
    name: str
    regex: str
    replacement: str


@dataclass
class MigrationPair:
    source_device: str
    target_device: str
    site: str = ""
    enabled: bool = True
    override_interface_mappings: Dict[str, str] = field(default_factory=dict)


@dataclass
class MigrationManifest:
    batch_name: str
    description: str
    preserve_target_mgmt_ip: bool
    target_mgmt_interface: str
    pattern_mappings: List[PatternMapping]
    migration_pairs: List[MigrationPair]
    filepath: str = ""


class ManifestLoader:
    """Loads and validates declarative migration manifests from YAML or JSON files."""

    @staticmethod
    def load(filepath: str) -> MigrationManifest:
        """Load YAML/JSON file and return structured MigrationManifest object."""
        # Check if manifest file exists
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Migration manifest file not found: {filepath}")

        logger.info("Loading migration manifest from '%s'...", filepath)

        # Read YAML or JSON manifest file content
        with open(filepath, "r", encoding="utf-8") as f:
            if filepath.endswith(".json"):
                raw_data = json.load(f)
            else:
                raw_data = yaml.safe_load(f)

        if not isinstance(raw_data, dict):
            raise ValueError("Invalid manifest format: Root element must be a dictionary/object.")

        # Extract metadata, default interface mapping rules, and device pairs
        metadata = raw_data.get("metadata", {})
        default_rules = raw_data.get("default_rules", {})
        pairs_raw = raw_data.get("migration_pairs", [])

        if not pairs_raw:
            raise ValueError("Manifest contains no migration pairs.")

        # Parse regex pattern mappings for interface transformations
        pattern_mappings = []
        for pm in default_rules.get("pattern_mappings", []):
            pattern_mappings.append(PatternMapping(
                name=pm.get("name", "Unnamed Rule"),
                regex=pm.get("regex", ""),
                replacement=pm.get("replacement", "")
            ))

        # Parse active source-to-target migration device pairs
        migration_pairs = []
        for pair_item in pairs_raw:
            # Skip pairs marked as disabled in manifest
            if not pair_item.get("enabled", True):
                logger.info("Skipping disabled pair: %s -> %s", pair_item.get("source_device"), pair_item.get("target_device"))
                continue

            src = pair_item.get("source_device")
            tgt = pair_item.get("target_device")

            if not src or not tgt:
                logger.warning("Skipping invalid pair entry lacking source_device or target_device: %s", pair_item)
                continue

            migration_pairs.append(MigrationPair(
                source_device=src,
                target_device=tgt,
                site=pair_item.get("site", ""),
                enabled=pair_item.get("enabled", True),
                override_interface_mappings=pair_item.get("override_interface_mappings", {})
            ))

        # Build and return immutable dataclass manifest object
        manifest = MigrationManifest(
            batch_name=metadata.get("batch_name", "unnamed_batch"),
            description=metadata.get("description", ""),
            preserve_target_mgmt_ip=default_rules.get("preserve_target_mgmt_ip", True),
            target_mgmt_interface=default_rules.get("target_mgmt_interface", "Vlan1"),
            pattern_mappings=pattern_mappings,
            migration_pairs=migration_pairs,
            filepath=filepath
        )

        logger.info(
            "Manifest '%s' loaded successfully with %d active migration pair(s).",
            manifest.batch_name,
            len(manifest.migration_pairs)
        )
        return manifest
