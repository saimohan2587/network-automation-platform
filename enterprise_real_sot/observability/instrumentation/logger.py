"""Network-Only Observability Logger Stubs.

Note: NAC Application log shipping to Loki has been removed.
This module provides safe no-op stubs to maintain backwards compatibility.
"""

def emit_pipeline_log(*args, **kwargs) -> None:
    """No-op stub for pipeline log emission."""
    pass
