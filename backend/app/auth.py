import base64
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import requests
from fastapi import HTTPException, Request, status

from app.storage.memory_store import LEGACY_USER_ID, get_auth_session


AUTH_COOKIE_NAME = "docuery_session"
STATE_COOKIE_NAME = "docuery_oauth_state"
SESSION_MAX_AGE_SECONDS = int(os.getenv("APP_SESSION_MAX_AGE_SECONDS", "2592000"))
OAUTH_TIMEOUT_SECONDS = 15
LOCAL_DEV_USER = {
    "user_id": os.getenv("DEV_USER_ID", LEGACY_USER_ID),
    "username": "Local Dev",
    "avatar_url": None,
}


def auth_required() -> bool:
    forced = os.getenv("REQUIRE_AUTH")

    if forced is not None:
        return forced.strip().lower() in {"1", "true", "yes", "on"}

    return bool(os.getenv("SPACE_HOST") or os.getenv("OAUTH_CLIENT_ID"))


def cookie_secure(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or "https" in forwarded_proto.split(",")


def session_expires_at() -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
    return expires_at.isoformat()


def oauth_configured() -> bool:
    return bool(os.getenv("OAUTH_CLIENT_ID") and os.getenv("OAUTH_CLIENT_SECRET"))


def get_current_user(request: Request) -> dict[str, Any]:
    if not auth_required():
        return LOCAL_DEV_USER

    session_token = request.cookies.get(AUTH_COOKIE_NAME)

    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to access your private workspace.",
        )

    user = get_auth_session(session_token)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session expired. Please sign in again.",
        )

    return user


def build_base_url(request: Request) -> str:
    space_host = os.getenv("SPACE_HOST")

    if space_host:
        return f"https://{space_host}"

    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto")
    host = forwarded_host or request.headers.get("host")
    scheme = forwarded_proto.split(",")[0].strip() if forwarded_proto else request.url.scheme
    return f"{scheme}://{host}"


def build_redirect_uri(request: Request) -> str:
    return f"{build_base_url(request)}/api/auth/callback"


def build_authorization_url(request: Request, state: str) -> str:
    client_id = os.getenv("OAUTH_CLIENT_ID")

    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="Hugging Face OAuth is not configured for this Space.",
        )

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": build_redirect_uri(request),
        "scope": "openid profile",
        "state": state,
    }
    return f"https://huggingface.co/oauth/authorize?{urlencode(params)}"


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def _openid_config() -> dict[str, Any]:
    provider = os.getenv("OPENID_PROVIDER_URL", "https://huggingface.co").rstrip("/")
    response = requests.get(
        f"{provider}/.well-known/openid-configuration",
        timeout=OAUTH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


def exchange_oauth_code(request: Request, code: str) -> dict[str, Any]:
    client_id = os.getenv("OAUTH_CLIENT_ID")
    client_secret = os.getenv("OAUTH_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail="Hugging Face OAuth is not configured for this Space.",
        )

    token_endpoint = _openid_config().get(
        "token_endpoint",
        "https://huggingface.co/oauth/token",
    )
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = requests.post(
        token_endpoint,
        data={
            "client_id": client_id,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": build_redirect_uri(request),
        },
        headers={"Authorization": f"Basic {credentials}"},
        timeout=OAUTH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict) or not data.get("access_token"):
        raise HTTPException(status_code=400, detail="OAuth token exchange failed.")

    return data


def fetch_oauth_user(access_token: str) -> dict[str, Any]:
    config = _openid_config()
    userinfo_endpoint = config.get(
        "userinfo_endpoint",
        "https://huggingface.co/oauth/userinfo",
    )
    response = requests.get(
        userinfo_endpoint,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=OAUTH_TIMEOUT_SECONDS,
    )

    if response.status_code >= 400:
        response = requests.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=OAUTH_TIMEOUT_SECONDS,
        )

    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Could not read OAuth user profile.")

    user_id = data.get("sub") or data.get("id") or data.get("name")
    username = data.get("preferred_username") or data.get("name") or data.get("fullname")
    avatar_url = data.get("picture") or data.get("avatarUrl") or data.get("avatar_url")

    if not user_id:
        raise HTTPException(status_code=400, detail="OAuth user profile is missing an ID.")

    return {
        "user_id": str(user_id),
        "username": str(username or "Hugging Face User"),
        "avatar_url": avatar_url,
    }
