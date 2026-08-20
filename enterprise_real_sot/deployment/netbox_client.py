"""
Purpose   : Low-level HTTP REST API client handling sessions, auth headers, retries, and pagination queries against NetBox.
Called By : device_selector.py, context_builder.py.
Calls Next: NetBox REST API (`http://localhost:8000/api/`).
"""

from typing import Dict, Any, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


from deployment.config import (
    NETBOX_URL,
    NETBOX_TOKEN,
    HTTP_TIMEOUT,
    HTTP_MAX_RETRIES,
    HTTP_BACKOFF_FACTOR
)
from deployment.logger import get_logger

logger = get_logger("NetBoxClient")

class NetBoxAPIError(Exception):
    """Custom exception raised when NetBox REST API calls fail."""
    pass

class NetBoxClient:
    """
    Enterprise NetBox REST API Client encapsulating HTTP session management,
    authorization, connection pooling, pagination handling, and retry logic.
    """

    def __init__(
        self,
        base_url: str = NETBOX_URL,
        token: str = NETBOX_TOKEN,
        timeout: int = HTTP_TIMEOUT
    ):
        # Normalize base URL by removing trailing slashes and appending a single slash for consistent path joining.
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token
        self.timeout = timeout
        # Create and store persistent HTTP session with connection pooling and authorization headers.
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Configures a requests.Session with retries and persistent auth headers."""
        # Create persistent session to reuse underlying TCP connections across multiple HTTP REST API requests.
        session = requests.Session()
        # Set default headers so every API call automatically includes authentication token and JSON content type.
        session.headers.update({
            "Authorization": f"Token {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

        # Define exponential backoff retry strategy for handling temporary server errors (500, 502, 503, 504).
        retries = Retry(
            total=HTTP_MAX_RETRIES,
            backoff_factor=HTTP_BACKOFF_FACTOR,
            status_forcelist=[500, 502, 503, 504]
        )
        # Mount HTTPAdapter with retry logic to http:// and https:// URLs for automatic transparent retries.
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _build_url(self, endpoint: str) -> str:
        """Constructs full URL from relative endpoint."""
        clean_endpoint = endpoint.lstrip("/")
        return f"{self.base_url}{clean_endpoint}"

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes a HTTP GET request against a NetBox REST API endpoint.
        Returns raw JSON dictionary response.
        """
        url = self._build_url(endpoint)
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            # Raise exception if NetBox returns a 4xx or 5xx HTTP status code, stopping invalid data processing.
            response.raise_for_status()
            # Convert JSON API response payload into a Python dictionary.
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP GET failed for '{url}' with params {params}: {e}")
            raise NetBoxAPIError(f"GET {url} failed: {e}") from e

    def get_all(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Executes a paginated HTTP GET request, following 'next' page links
        until all result items are retrieved. Returns a flattened list of items.
        """
        url = self._build_url(endpoint)
        all_results: List[Dict[str, Any]] = []
        current_params = params.copy() if params else {}
        
        # Loop repeatedly as long as NetBox returns a 'next' page URL in the response payload.
        while url:
            try:
                response = self.session.get(url, params=current_params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                
                if isinstance(payload, dict) and "results" in payload:
                    all_results.extend(payload["results"])
                    # Extract next page URL from NetBox payload, resetting params as next URL embeds query string.
                    url = payload.get("next")
                    current_params = {}  # Next URL already includes page query params
                elif isinstance(payload, list):
                    all_results.extend(payload)
                    break
                else:
                    break
            except requests.exceptions.RequestException as e:
                logger.error(f"Paginated GET failed for '{url}': {e}")
                raise NetBoxAPIError(f"Paginated GET {url} failed: {e}") from e

        return all_results

    def post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a HTTP POST request against a NetBox REST API endpoint.
        """
        url = self._build_url(endpoint)
        try:
            response = self.session.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP POST failed for '{url}': {e}")
            raise NetBoxAPIError(f"POST {url} failed: {e}") from e

    def patch(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a HTTP PATCH request against a NetBox REST API endpoint.
        """
        url = self._build_url(endpoint)
        try:
            # Perform HTTP PATCH request to update specific fields on a NetBox resource.
            response = self.session.patch(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP PATCH failed for '{url}': {e}")
            raise NetBoxAPIError(f"PATCH {url} failed: {e}") from e

