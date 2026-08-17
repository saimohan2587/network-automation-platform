"""
Purpose   : Resolves user device selection criteria (device names, site filters) into target device records from NetBox.
Called By : main.py (`DeploymentOrchestrator.run()`).
Calls Next: netbox_client.py (`NetBoxClient.get_all("dcim/devices/")`).
"""

from typing import List, Dict, Any, Optional, Union
from deployment.netbox_client import NetBoxClient
from deployment.logger import get_logger


logger = get_logger("DeviceSelector")

class DeviceSelector:
    """
    Enterprise Device Selector module responsible for querying target devices
    from NetBox REST API based on dynamic filter criteria.
    """

    def __init__(self, netbox_client: NetBoxClient):
        # Inject the NetBox REST client dependency to perform device queries.
        self.client = netbox_client

    def _normalize_filter_value(self, value: Any) -> Any:
        """
        Converts lists or tuples into comma-separated strings for NetBox API queries.
        """
        # Convert multi-select filter lists (e.g. multiple site names) into string arrays formatted for NetBox REST API.
        if isinstance(value, (list, tuple, set)):
            return [str(v) for v in value]
        return str(value)

    def build_query_params(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dynamically maps user/CLI selection criteria into NetBox REST API query parameters.
        Supports single values, lists, and dynamic custom field parameters.
        """
        params: Dict[str, Any] = {}

        # Standard dictionary mapping user CLI filter keywords (like 'device' or 'sites') to exact NetBox REST API query parameter names.
        param_mapping = {
            "name": "name",
            "names": "name",
            "device": "name",
            "devices": "name",
            "site": "site",
            "sites": "site",
            "role": "role",
            "roles": "role",
            "platform": "platform",
            "platforms": "platform",
            "tag": "tag",
            "tags": "tag",
            "status": "status",
            "region": "region",
            "tenant": "tenant"
        }

        for key, value in criteria.items():
            # Skip empty or unassigned selection criteria so empty parameters aren't sent to NetBox.
            if value is None or value == "" or value == []:
                continue

            normalized_key = key.lower()

            if normalized_key in param_mapping:
                api_param_name = param_mapping[normalized_key]
                params[api_param_name] = self._normalize_filter_value(value)
            elif normalized_key == "custom_fields" and isinstance(value, dict):
                # Format nested custom field dictionary into NetBox API expected format (e.g. cf_environment=production).
                for cf_key, cf_val in value.items():
                    cf_param = cf_key if cf_key.startswith("cf_") else f"cf_{cf_key}"
                    params[cf_param] = self._normalize_filter_value(cf_val)
            elif normalized_key.startswith("cf_"):
                # Handle direct custom field query parameters prefixed with 'cf_'.
                params[normalized_key] = self._normalize_filter_value(value)
            else:
                # Pass through any generic parameter directly to NetBox REST API.
                params[key] = self._normalize_filter_value(value)

        return params

    def select_devices(self, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Queries NetBox API endpoint 'dcim/devices/' with dynamic filter parameters
        and returns matching device objects.
        """
        # Build query parameters dictionary from user filter criteria.
        params = self.build_query_params(criteria)
        logger.info(f"Selecting devices from NetBox with parameters: {params}")

        try:
            # Query NetBox dcim/devices/ REST API endpoint, automatically iterating over all result pages.
            # Returns list of target device dictionary objects to main.py.
            devices = self.client.get_all("dcim/devices/", params=params)
            logger.info(f"Retrieved {len(devices)} device(s) matching criteria.")
            return devices
        except Exception as e:
            logger.error(f"Failed to query devices from NetBox: {e}")
            raise

