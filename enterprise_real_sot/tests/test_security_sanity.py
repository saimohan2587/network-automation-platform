"""
Security sanity checks for CI.

IMPORTANT - what this file is NOT: this is a lightweight, regex/pattern-based
sanity check, not a real secret-detection engine (no entropy analysis, no
provider-specific token-format detection, no git-history scanning). It exists
to catch the specific, concrete mistakes already found and fixed once in this
project's own history (a real secret committed to .env.example, a hardcoded
SNMP community string, a hardcoded Grafana password) from silently
regressing - not to provide general confidence that "no secrets exist
anywhere". A real secret that doesn't match these specific patterns will NOT
be caught here. Treat a pass as "the known mistakes haven't recurred", not as
"this repository has been security-scanned".
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT_ROOT = REPO_ROOT.parent  # the actual .git repository root is one level up

# Patterns that look like a real, live secret value rather than a placeholder.
# Deliberately narrow and documented, not an attempt at general secret detection.
_SUSPICIOUS_VALUE_PATTERNS = [
    re.compile(r"^nbt_[A-Za-z0-9._-]{20,}$"),          # a real-looking NetBox token
    re.compile(r"^[a-f0-9]{32,}$", re.IGNORECASE),      # a bare long hex string (sys_id/token-shaped)
]

_PLACEHOLDER_ALLOWLIST = {
    "0123456789abcdef0123456789abcdef01234567",  # the deliberate example token in .env.example
}


def _git_check_ignore(relative_path: str) -> bool:
    """Returns True if `git check-ignore` confirms the path is ignored."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative_path],
        cwd=GIT_ROOT,
        capture_output=True,
    )
    return result.returncode == 0


def test_real_env_file_is_gitignored():
    assert _git_check_ignore("enterprise_real_sot/.env"), (
        ".env must be git-ignored - if this fails, real secrets could be committed"
    )


def test_rendered_snmp_config_is_gitignored():
    assert _git_check_ignore("enterprise_real_sot/observability/snmp_exporter/snmp.yml"), (
        "the rendered snmp.yml (containing the real SNMP community value) must be git-ignored; "
        "only snmp.yml.template (the placeholder version) should ever be tracked"
    )


def test_env_example_contains_no_live_looking_secrets():
    env_example = REPO_ROOT / ".env.example"
    assert env_example.exists()

    offending_lines = []
    for line_no, line in enumerate(env_example.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if not value or value in _PLACEHOLDER_ALLOWLIST:
            continue
        for pattern in _SUSPICIOUS_VALUE_PATTERNS:
            if pattern.match(value):
                offending_lines.append((line_no, key))

    assert not offending_lines, (
        f".env.example appears to contain a live-looking secret value on line(s): {offending_lines}. "
        ".env.example must contain variable names and placeholders only."
    )


def test_no_obvious_hardcoded_snmp_community_in_tracked_python_or_yaml_source():
    """
    Regression guard: the community string must not reappear hardcoded in any
    tracked .py file, or in any tracked YAML file OTHER than the intentionally
    real-valued device-facing config generation output under csv/ (which is
    legitimate NetBox-sourced business config data, not an application secret).
    """
    result = subprocess.run(
        ["git", "ls-files", "*.py", "*.yml", "*.yaml"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    tracked_files = [REPO_ROOT / p for p in result.stdout.splitlines() if p]

    offenders = []
    for path in tracked_files:
        if not path.exists():
            continue
        if "csv" in path.parts or path.name.endswith(".template"):
            continue
        # Test fixtures legitimately contain realistic-looking-but-synthetic
        # sample values (e.g. tests/ci_runner.py's MockConnection running-config
        # text) - this is not a real credential leak, confirmed during the
        # security-hardening audit. Real application/config code is not
        # excluded by this rule.
        if "tests" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "NOC-ReadOnly" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, f"Found a hardcoded SNMP community string in tracked source: {offenders}"


ALL_TESTS = [
    test_real_env_file_is_gitignored,
    test_rendered_snmp_config_is_gitignored,
    test_env_example_contains_no_live_looking_secrets,
    test_no_obvious_hardcoded_snmp_community_in_tracked_python_or_yaml_source,
]


if __name__ == "__main__":
    for test in ALL_TESTS:
        test()
        print(f"✓ {test.__name__}")
    print("ALL SECURITY SANITY CHECKS PASSED (see module docstring for scope/limits)")
