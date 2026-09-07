"""Network-Only Observability Instrumentation Stubs.

Note: NAC Application metrics and CD telemetry have been removed from the pipeline.
This module provides safe no-op stubs to maintain backwards compatibility.
"""

def start_app_metrics_exporter(port: int = 8001) -> bool:
    """No-op stub for NAC application metrics exporter."""
    return True

def record_netbox_api_request(*args, **kwargs) -> None:
    pass

def record_netbox_sync(*args, **kwargs) -> None:
    pass

def record_gatekeeper_assessment(*args, **kwargs) -> None:
    pass

def record_deployment_start(*args, **kwargs) -> None:
    pass

def record_deployment_result(*args, **kwargs) -> None:
    pass

def record_compliance_result(*args, **kwargs) -> None:
    pass
