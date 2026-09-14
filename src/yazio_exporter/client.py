"""
HTTP client wrapper using requests.Session.
"""

import time
from collections.abc import Callable

import requests

from yazio_exporter.constants import API_VERSION, BASE_URL, MAX_RETRIES, REQUEST_TIMEOUT
from yazio_exporter.exceptions import APIError, AuthenticationError


class YazioClient:
    """HTTP client for Yazio API with session management."""

    def __init__(self, base_url: str = BASE_URL, api_version: str = API_VERSION):
        self.base_url = base_url
        self.api_version = api_version
        self.session = requests.Session()
        self.session.timeout = REQUEST_TIMEOUT
        # Optional self-imposed throttle (sync mode): called before every request.
        self.throttle: Callable[[], None] | None = None
        # Optional token refresher: returns a new access token, tried once on 401.
        self.refresher: Callable[[], str] | None = None

    def set_token(self, token: str) -> None:
        """Set the authorization token for all requests."""
        self.session.headers["Authorization"] = f"Bearer {token}"

    def get_url(self, endpoint: str) -> str:
        """Construct full URL from endpoint."""
        if endpoint.startswith("/"):
            endpoint = endpoint[1:]
        return f"{self.base_url}/{self.api_version}/{endpoint}"

    def get(self, endpoint: str, max_retries: int = MAX_RETRIES, **kwargs) -> requests.Response:
        """
        Make a GET request with enhanced error handling and retry logic.

        Args:
            endpoint: API endpoint (e.g., "/user" or "user")
            max_retries: Maximum number of retry attempts for 5xx errors (default: 3)
            **kwargs: Additional arguments to pass to requests.get()

        Returns:
            Response object if successful

        Raises:
            AuthenticationError: On 401 responses (expired/invalid token)
            APIError: On other HTTP error responses (4xx, 5xx)
            requests.Timeout: If request times out
        """
        url = self.get_url(endpoint)

        # Set timeout if not provided in kwargs
        if "timeout" not in kwargs:
            kwargs["timeout"] = REQUEST_TIMEOUT

        last_error = None
        refreshed = False

        for attempt in range(max_retries):
            try:
                if self.throttle is not None:
                    self.throttle()
                response = self.session.get(url, **kwargs)

                # Expired token: refresh silently once, then re-authenticate loudly
                if response.status_code == 401 and self.refresher is not None and not refreshed:
                    refreshed = True
                    self.set_token(self.refresher())
                    continue

                # Rate limited: honour Retry-After, otherwise exponential backoff
                if response.status_code == 429:
                    last_error = APIError(
                        f"HTTP 429 rate limited for URL: {url}",
                        status_code=429,
                        url=url,
                    )
                    if attempt < max_retries - 1:
                        retry_after = response.headers.get("Retry-After")
                        backoff_time = (
                            float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1)
                        )
                        time.sleep(backoff_time)
                        continue
                    raise last_error

                # Check for 401 expired token errors
                if response.status_code == 401:
                    error_msg = f"HTTP 401 error for URL: {url}"
                    try:
                        error_data = response.json()
                        if "error" in error_data or "message" in error_data:
                            error_msg = (
                                "HTTP 401 Unauthorized: Token may have expired. "
                                "Please run 'yazio-exporter login' again to refresh your authentication."
                            )
                    except (ValueError, KeyError):
                        error_msg = (
                            "HTTP 401 Unauthorized: Token may have expired. "
                            "Please run 'yazio-exporter login' again to refresh your authentication."
                        )
                    raise AuthenticationError(error_msg)

                # Retry on 5xx server errors
                if 500 <= response.status_code < 600:
                    last_error = APIError(
                        f"HTTP {response.status_code} error for URL: {url}",
                        status_code=response.status_code,
                        url=url,
                    )

                    if attempt < max_retries - 1:
                        backoff_time = 2**attempt
                        time.sleep(backoff_time)
                        continue
                    else:
                        raise last_error

                # Other non-OK responses (4xx except 401, etc.)
                if not response.ok:
                    raise APIError(
                        f"HTTP {response.status_code} error for URL: {url}",
                        status_code=response.status_code,
                        url=url,
                    )

                return response

            except requests.Timeout:
                raise
            except (AuthenticationError, APIError):
                raise
            except requests.RequestException as e:
                last_error = e
                if attempt < max_retries - 1:
                    backoff_time = 2**attempt
                    time.sleep(backoff_time)
                    continue
                else:
                    raise
