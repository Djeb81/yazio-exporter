"""
Authentication: login and token management.
"""

import json
import os
import time

import requests

from yazio_exporter.client import YazioClient
from yazio_exporter.exceptions import AuthenticationError

# Hardcoded Yazio client credentials (from API spec)
CLIENT_ID = "1_4hiybetvfksgw40o0sog4s884kwc840wwso8go4k8c04goo4c"
CLIENT_SECRET = "6rok2m65xuskgkgogw40wkkk8sw0osg84s8cggsc4woos4s8o"


def login_full(email: str, password: str, client: YazioClient = None) -> dict:
    """
    Authenticate with Yazio API and return the whole token payload
    (access_token, refresh_token, expires_in, ...) plus a computed expires_at.

    Raises:
        AuthenticationError: If authentication fails
    """
    if client is None:
        client = YazioClient()

    url = f"{client.base_url}/{client.api_version}/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "username": email,
        "password": password,
        "grant_type": "password",
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as e:
        raise AuthenticationError(str(e)) from e

    data = response.json()
    if "access_token" not in data:
        raise AuthenticationError("oauth/token response has no access_token")
    if "expires_in" in data:
        data["expires_at"] = int(time.time()) + int(data["expires_in"])
    return data


def refresh_access_token(refresh_token: str, client: YazioClient = None) -> dict:
    """
    Exchange a refresh token for a new token payload (OAuth2 refresh_token grant,
    application/x-www-form-urlencoded).

    Raises:
        AuthenticationError: If the refresh is rejected (re-login required)
    """
    if client is None:
        client = YazioClient()

    url = f"{client.base_url}/{client.api_version}/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    try:
        response = requests.post(url, data=payload, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as e:
        raise AuthenticationError(f"token refresh rejected, run 'yazio-exporter login' again: {e}") from e

    data = response.json()
    if "access_token" not in data:
        raise AuthenticationError("refresh response has no access_token")
    if "expires_in" in data:
        data["expires_at"] = int(time.time()) + int(data["expires_in"])
    return data


def save_token_file(data: dict, token_file: str) -> None:
    """Write a token payload as JSON with 0600 permissions."""
    with open(token_file, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.chmod(token_file, 0o600)


def load_token_file(token_file: str) -> dict:
    """
    Load a token file. Accepts the legacy plain-text access token (no refresh
    possible) or the JSON payload written by `login`.
    """
    with open(token_file) as f:
        raw = f.read().strip()
    if not raw:
        raise ValueError(f"Token file is empty: {token_file}")
    if raw.startswith("{"):
        data = json.loads(raw)
        if "access_token" not in data:
            raise ValueError(f"Token file has no access_token: {token_file}")
        return data
    return {"access_token": raw}


def login(email: str, password: str, client: YazioClient = None) -> str:
    """
    Authenticate with Yazio API and return access token.

    Args:
        email: User email
        password: User password
        client: Optional YazioClient (uses its base_url/api_version)

    Returns:
        Access token string

    Raises:
        AuthenticationError: If authentication fails
    """
    return login_full(email, password, client)["access_token"]


def login_and_save(email: str, password: str, token_file: str) -> str:
    """
    Login and save token to file with restrictive permissions.

    Args:
        email: User email
        password: User password
        token_file: Path to save token

    Returns:
        Access token string

    Note:
        File is created with 0600 permissions (owner read/write only) and holds the
        JSON payload (access + refresh token) so that `sync` can renew silently.
    """
    data = login_full(email, password)
    save_token_file(data, token_file)
    return data["access_token"]


def load_token(token_file: str) -> str:
    """
    Load access token from a file.

    Args:
        token_file: Path to token file

    Returns:
        Access token string

    Raises:
        FileNotFoundError: If token file does not exist
        ValueError: If token file is empty
    """
    return load_token_file(token_file)["access_token"]


def make_authenticated_client(token_file: str) -> YazioClient:
    """
    Create an authenticated YazioClient from a token file.

    Args:
        token_file: Path to token file

    Returns:
        Authenticated YazioClient instance
    """
    data = load_token_file(token_file)
    client = YazioClient()
    client.set_token(data["access_token"])

    refresh = data.get("refresh_token")
    if refresh:

        def _refresh() -> str:
            new_data = refresh_access_token(refresh, client)
            merged = {**data, **new_data}
            save_token_file(merged, token_file)
            data.update(merged)
            return merged["access_token"]

        client.refresher = _refresh
    return client
