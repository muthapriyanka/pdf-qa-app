import base64
import os
import secrets
from dataclasses import dataclass
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


@dataclass(frozen=True)
class OAuthProvider:
    provider_id: str
    label: str
    client_id_env: str
    client_secret_env: str
    issuer_url: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str
    id_prefix: str
    token_auth_method: str = "basic"
    fallback_userinfo_url: str | None = None


OAUTH_PROVIDERS = {
    "huggingface": OAuthProvider(
        provider_id="huggingface",
        label="Hugging Face",
        client_id_env="OAUTH_CLIENT_ID",
        client_secret_env="OAUTH_CLIENT_SECRET",
        issuer_url=os.getenv("OPENID_PROVIDER_URL", "https://huggingface.co"),
        authorize_url="https://huggingface.co/oauth/authorize",
        token_url="https://huggingface.co/oauth/token",
        userinfo_url="https://huggingface.co/oauth/userinfo",
        fallback_userinfo_url="https://huggingface.co/api/whoami-v2",
        scope="openid profile",
        id_prefix="",
    ),
    "google": OAuthProvider(
        provider_id="google",
        label="Google",
        client_id_env="GOOGLE_CLIENT_ID",
        client_secret_env="GOOGLE_CLIENT_SECRET",
        issuer_url="https://accounts.google.com",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scope="openid profile email",
        id_prefix="google",
        token_auth_method="post",
    ),
}


def auth_required() -> bool:
    forced = os.getenv("REQUIRE_AUTH")

    if forced is not None:
        return forced.strip().lower() in {"1", "true", "yes", "on"}

    return bool(os.getenv("SPACE_HOST") or configured_oauth_providers())


def cookie_secure(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or "https" in forwarded_proto.split(",")


def session_expires_at() -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
    return expires_at.isoformat()


def oauth_configured() -> bool:
    return bool(configured_oauth_providers())


def get_oauth_provider(provider_id: str) -> OAuthProvider:
    provider = OAUTH_PROVIDERS.get(provider_id)

    if not provider:
        raise HTTPException(status_code=404, detail="OAuth provider was not found.")

    return provider


def provider_configured(provider: OAuthProvider) -> bool:
    return bool(os.getenv(provider.client_id_env) and os.getenv(provider.client_secret_env))


def configured_oauth_providers() -> list[dict[str, str]]:
    return [
        {"id": provider.provider_id, "label": provider.label}
        for provider in OAUTH_PROVIDERS.values()
        if provider_configured(provider)
    ]


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


def build_redirect_uri(request: Request, provider_id: str = "huggingface") -> str:
    if provider_id == "huggingface":
        return f"{build_base_url(request)}/api/auth/callback"

    return f"{build_base_url(request)}/api/auth/{provider_id}/callback"


def build_authorization_url(
    request: Request,
    state: str,
    provider_id: str = "huggingface",
) -> str:
    provider = get_oauth_provider(provider_id)
    client_id = os.getenv(provider.client_id_env)

    if not client_id:
        raise HTTPException(
            status_code=500,
            detail=f"{provider.label} OAuth is not configured for this deployment.",
        )

    config = _openid_config(provider)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": build_redirect_uri(request, provider.provider_id),
        "scope": provider.scope,
        "state": state,
    }
    return f"{config.get('authorization_endpoint', provider.authorize_url)}?{urlencode(params)}"


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def _openid_config(provider: OAuthProvider) -> dict[str, Any]:
    provider_url = provider.issuer_url.rstrip("/")
    response = requests.get(
        f"{provider_url}/.well-known/openid-configuration",
        timeout=OAUTH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


def exchange_oauth_code(
    request: Request,
    code: str,
    provider_id: str = "huggingface",
) -> dict[str, Any]:
    provider = get_oauth_provider(provider_id)
    client_id = os.getenv(provider.client_id_env)
    client_secret = os.getenv(provider.client_secret_env)

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail=f"{provider.label} OAuth is not configured for this deployment.",
        )

    token_endpoint = _openid_config(provider).get(
        "token_endpoint",
        provider.token_url,
    )
    payload = {
        "client_id": client_id,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": build_redirect_uri(request, provider.provider_id),
    }
    headers = {}

    if provider.token_auth_method == "basic":
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"
    else:
        payload["client_secret"] = client_secret

    response = requests.post(
        token_endpoint,
        data=payload,
        headers=headers,
        timeout=OAUTH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict) or not data.get("access_token"):
        raise HTTPException(status_code=400, detail="OAuth token exchange failed.")

    return data


def fetch_oauth_user(
    access_token: str,
    provider_id: str = "huggingface",
) -> dict[str, Any]:
    provider = get_oauth_provider(provider_id)
    config = _openid_config(provider)
    userinfo_endpoint = config.get(
        "userinfo_endpoint",
        provider.userinfo_url,
    )
    response = requests.get(
        userinfo_endpoint,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=OAUTH_TIMEOUT_SECONDS,
    )

    if response.status_code >= 400 and provider.fallback_userinfo_url:
        response = requests.get(
            provider.fallback_userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=OAUTH_TIMEOUT_SECONDS,
        )

    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Could not read OAuth user profile.")

    user_id = data.get("sub") or data.get("id") or data.get("name")
    username = (
        data.get("preferred_username")
        or data.get("name")
        or data.get("fullname")
        or data.get("email")
    )
    avatar_url = data.get("picture") or data.get("avatarUrl") or data.get("avatar_url")

    if not user_id:
        raise HTTPException(status_code=400, detail="OAuth user profile is missing an ID.")

    scoped_user_id = f"{provider.id_prefix}:{user_id}" if provider.id_prefix else str(user_id)

    return {
        "user_id": scoped_user_id,
        "username": str(username or f"{provider.label} User"),
        "avatar_url": avatar_url,
    }
