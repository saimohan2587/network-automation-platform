"""Interface mapping engine for device_migration package."""

import re
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass

from device_migration.manifest_loader import MigrationManifest, MigrationPair
from device_migration.logger import get_logger

logger = get_logger("InterfaceMapper")


@dataclass
class MappedInterface:
    source_interface: str
    target_interface: Optional[str]
    mapped: bool
    mapping_strategy: str  # "override", "pattern", "netbox_inventory", "unmapped"
    notes: str = ""


class InterfaceMapper:
    """Dynamic hardware interface mapping engine."""

    def __init__(self, manifest: MigrationManifest, pair: MigrationPair):
        self.manifest = manifest
        self.pair = pair
        # Load explicit pair overrides and pattern regex rules
        self.overrides = pair.override_interface_mappings or {}
        self.pattern_rules = manifest.pattern_mappings

    def map_interface(self, src_iface: str) -> MappedInterface:
        """Map a single source interface using Tier 1 (Override) -> Tier 2 (Pattern) strategy cascade."""
        if not src_iface:
            return MappedInterface(src_iface, None, False, "unmapped", "Empty source interface name")

        clean_src = src_iface.strip()

        # Tier 1: Check explicit per-pair override mappings first
        if clean_src in self.overrides:
            tgt = self.overrides[clean_src]
            return MappedInterface(clean_src, tgt, True, "override", f"Explicit override to {tgt}")

        # Tier 2: Check regex pattern rules defined in manifest YAML
        for rule in self.pattern_rules:
            if not rule.regex:
                continue
            match = re.match(rule.regex, clean_src, re.IGNORECASE)
            if match:
                try:
                    # Apply regex replacement to convert old port name (Gi3/0/1) to new port name (Gi1/0/1)
                    tgt = re.sub(rule.regex, rule.replacement, clean_src, flags=re.IGNORECASE)
                    return MappedInterface(clean_src, tgt, True, "pattern", f"Matched rule '{rule.name}' -> {tgt}")
                except Exception as err:
                    logger.warning("Regex substitution error on rule '%s' for '%s': %s", rule.name, clean_src, err)

        # Unmapped if no override or regex rule matched
        return MappedInterface(clean_src, None, False, "unmapped", "No matching pattern rule or override found")

    def build_mapping_matrix(self, source_interfaces: List[str]) -> Tuple[List[MappedInterface], List[str]]:
        """
        Build mapping matrix for list of source interfaces.
        Returns (mapped_list, unmapped_source_list).
        """
        mapped_matrix: List[MappedInterface] = []
        unmapped_list: List[str] = []

        # Iterate over all discovered source interfaces and map each one
        for src_iface in sorted(source_interfaces):
            m = self.map_interface(src_iface)
            mapped_matrix.append(m)
            if not m.mapped:
                unmapped_list.append(src_iface)

        return mapped_matrix, unmapped_list
