"""
Unit tests for deployment/artifact_manager.py's Phase 0 artifact foundation:
write_manifest() / verify_manifest(). No NetBox, no SSH, no device -- these
exercise the manifest contract directly against a temp artifact directory
with hand-crafted AssessmentResult-shaped stand-ins, the same way
test_rollback_manager.py exercises rollback_manager.py in isolation.
"""

import tempfile
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Any, Mapping, Optional

from deployment.artifact_manager import write_manifest, verify_manifest


@dataclass(frozen=True)
class _FakeAssessment:
    """Minimal stand-in for deployment.main.AssessmentResult -- write_manifest()
    only reads .device_name / .device / .generated_configuration / .failure_reason
    via getattr(), so this avoids importing the full orchestrator for a unit test."""

    device_name: str
    device: Optional[Mapping[str, Any]] = None
    generated_configuration: Optional[str] = None
    is_candidate: bool = False
    failure_reason: Optional[str] = None


def _write_candidate_cfg(artifact_dir: Path, device_name: str, content: str) -> None:
    (artifact_dir / f"{device_name}.cfg").write_text(content, encoding="utf-8")


def test_valid_artifact_with_all_devices_passing_is_deployable_and_verifies():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        candidates = [
            _FakeAssessment(device_name="sw-access-01", device={"id": 1, "last_updated": "2026-01-01T00:00:00Z"}, is_candidate=True),
            _FakeAssessment(device_name="sw-access-02", device={"id": 2, "last_updated": "2026-01-01T00:00:00Z"}, is_candidate=True),
        ]
        _write_candidate_cfg(artifact_dir, "sw-access-01", "hostname sw-access-01\n")
        _write_candidate_cfg(artifact_dir, "sw-access-02", "hostname sw-access-02\n")

        manifest_path = write_manifest(
            artifact_dir=artifact_dir,
            batch_id="20260101_000000_batch-2",
            timestamp=datetime(2026, 1, 1),
            candidates=candidates,
            skipped=[],
        )
        assert manifest_path.exists()

        result = verify_manifest(artifact_dir)
        assert result["valid"] is True, result["errors"]
        assert result["manifest"]["deployable"] is True
        assert len(result["manifest"]["devices"]) == 2
        assert result["manifest"]["excluded_devices"] == []


def test_one_tampered_config_byte_fails_verification():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        candidates = [_FakeAssessment(device_name="sw-access-01", device={"id": 1}, is_candidate=True)]
        _write_candidate_cfg(artifact_dir, "sw-access-01", "hostname sw-access-01\n")

        write_manifest(
            artifact_dir=artifact_dir,
            batch_id="batch-1",
            timestamp=datetime(2026, 1, 1),
            candidates=candidates,
            skipped=[],
        )

        # Flip a single byte in the deployed config after the manifest was sealed.
        cfg_path = artifact_dir / "sw-access-01.cfg"
        original = cfg_path.read_text(encoding="utf-8")
        tampered = original.replace("sw-access-01", "sw-access-0X", 1)
        assert tampered != original
        cfg_path.write_text(tampered, encoding="utf-8")

        result = verify_manifest(artifact_dir)
        assert result["valid"] is False
        assert any("Hash mismatch" in e for e in result["errors"])
        assert any("Batch hash mismatch" in e for e in result["errors"])


def test_one_failed_device_is_excluded_not_deployable_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        candidates = [_FakeAssessment(device_name="sw-access-01", device={"id": 1}, is_candidate=True)]
        skipped = [
            _FakeAssessment(
                device_name="sw-access-02",
                device={"id": 2},
                is_candidate=False,
                failure_reason="Pre-deployment validation failed: interface not found",
            )
        ]
        _write_candidate_cfg(artifact_dir, "sw-access-01", "hostname sw-access-01\n")
        # Note: no .cfg file is written for the skipped device -- it must never get one.

        write_manifest(
            artifact_dir=artifact_dir,
            batch_id="batch-mixed",
            timestamp=datetime(2026, 1, 1),
            candidates=candidates,
            skipped=skipped,
        )

        result = verify_manifest(artifact_dir)
        assert result["valid"] is True, result["errors"]
        manifest = result["manifest"]
        assert manifest["deployable"] is True
        device_names = [d["device_name"] for d in manifest["devices"]]
        assert device_names == ["sw-access-01"]
        excluded_names = [d["device_name"] for d in manifest["excluded_devices"]]
        assert excluded_names == ["sw-access-02"]
        assert manifest["excluded_devices"][0]["device_id"] == 2
        assert "interface not found" in manifest["excluded_devices"][0]["reason"]
        assert not (artifact_dir / "sw-access-02.cfg").exists()


def test_all_devices_failing_produces_non_deployable_manifest_that_fails_verification():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        skipped = [
            _FakeAssessment(device_name="sw-access-01", device={"id": 1}, is_candidate=False, failure_reason="bad config"),
            _FakeAssessment(device_name="sw-access-02", device={"id": 2}, is_candidate=False, failure_reason="bad config"),
        ]

        write_manifest(
            artifact_dir=artifact_dir,
            batch_id="batch-all-failed",
            timestamp=datetime(2026, 1, 1),
            candidates=[],
            skipped=skipped,
        )

        result = verify_manifest(artifact_dir)
        assert result["valid"] is False
        assert result["manifest"]["deployable"] is False
        assert result["manifest"]["devices"] == []
        assert any("deployable=false" in e for e in result["errors"])


def test_missing_config_file_fails_verification():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        candidates = [_FakeAssessment(device_name="sw-access-01", device={"id": 1}, is_candidate=True)]
        _write_candidate_cfg(artifact_dir, "sw-access-01", "hostname sw-access-01\n")

        write_manifest(
            artifact_dir=artifact_dir,
            batch_id="batch-1",
            timestamp=datetime(2026, 1, 1),
            candidates=candidates,
            skipped=[],
        )

        # Delete the config file after the manifest was sealed.
        (artifact_dir / "sw-access-01.cfg").unlink()

        result = verify_manifest(artifact_dir)
        assert result["valid"] is False
        assert any("Missing config file" in e for e in result["errors"])


def test_batch_hash_is_deterministic_regardless_of_candidate_order():
    with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
        dir_a, dir_b = Path(tmp_a), Path(tmp_b)
        dev1 = _FakeAssessment(device_name="sw-access-01", device={"id": 1}, is_candidate=True)
        dev2 = _FakeAssessment(device_name="sw-access-02", device={"id": 2}, is_candidate=True)

        for d in (dir_a, dir_b):
            _write_candidate_cfg(d, "sw-access-01", "hostname sw-access-01\n")
            _write_candidate_cfg(d, "sw-access-02", "hostname sw-access-02\n")

        write_manifest(artifact_dir=dir_a, batch_id="b", timestamp=datetime(2026, 1, 1), candidates=[dev1, dev2], skipped=[])
        write_manifest(artifact_dir=dir_b, batch_id="b", timestamp=datetime(2026, 1, 1), candidates=[dev2, dev1], skipped=[])

        import json
        manifest_a = json.loads((dir_a / "manifest.json").read_text(encoding="utf-8"))
        manifest_b = json.loads((dir_b / "manifest.json").read_text(encoding="utf-8"))
        assert manifest_a["batch_hash"] == manifest_b["batch_hash"]
        assert manifest_a["batch_hash"] is not None


def test_verify_manifest_missing_manifest_file_fails():
    with tempfile.TemporaryDirectory() as tmp:
        result = verify_manifest(Path(tmp))
        assert result["valid"] is False
        assert "manifest.json not found" in result["errors"][0]


def test_git_commit_sha_prefers_github_sha_env_var():
    import os
    from deployment import artifact_manager

    previous = os.environ.get("GITHUB_SHA")
    os.environ["GITHUB_SHA"] = "deadbeefcafefeed0000000000000000000000"
    try:
        assert artifact_manager._git_commit_sha() == "deadbeefcafefeed0000000000000000000000"
    finally:
        if previous is None:
            os.environ.pop("GITHUB_SHA", None)
        else:
            os.environ["GITHUB_SHA"] = previous


ALL_TESTS = [
    test_valid_artifact_with_all_devices_passing_is_deployable_and_verifies,
    test_one_tampered_config_byte_fails_verification,
    test_one_failed_device_is_excluded_not_deployable_candidate,
    test_all_devices_failing_produces_non_deployable_manifest_that_fails_verification,
    test_missing_config_file_fails_verification,
    test_batch_hash_is_deterministic_regardless_of_candidate_order,
    test_verify_manifest_missing_manifest_file_fails,
    test_git_commit_sha_prefers_github_sha_env_var,
]


if __name__ == "__main__":
    for test in ALL_TESTS:
        test()
        print(f"✓ {test.__name__}")
    print("ALL ARTIFACT MANAGER UNIT TESTS PASSED")
