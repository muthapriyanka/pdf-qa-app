from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth import (
    AUTH_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    STATE_COOKIE_NAME,
    auth_required,
    build_authorization_url,
    cookie_secure,
    exchange_oauth_code,
    fetch_oauth_user,
    generate_oauth_state,
    generate_session_token,
    get_current_user,
    oauth_configured,
    session_expires_at,
)
from app.storage.memory_store import create_auth_session, delete_auth_session


router = APIRouter()


@router.get("/auth/status")
def auth_status(request: Request):
    required = auth_required()

    if not required:
        user = get_current_user(request)
        return {
            "authenticated": True,
            "required": False,
            "configured": oauth_configured(),
            "user": user,
        }

    try:
        user = get_current_user(request)
    except HTTPException:
        return {
            "authenticated": False,
            "required": True,
            "configured": oauth_configured(),
            "user": None,
        }

    return {
        "authenticated": True,
        "required": True,
        "configured": oauth_configured(),
        "user": user,
    }


@router.get("/auth/login")
def login(request: Request):
    if not auth_required():
        return RedirectResponse(url="/")

    state = generate_oauth_state()
    response = RedirectResponse(url=build_authorization_url(request, state))
    response.set_cookie(
        STATE_COOKIE_NAME,
        state,
        httponly=True,
        secure=cookie_secure(request),
        samesite="lax",
        max_age=600,
    )
    return response


@router.get("/auth/callback")
def auth_callback(request: Request, code: str | None = None, state: str | None = None):
    expected_state = request.cookies.get(STATE_COOKIE_NAME)

    if not code or not state or not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth callback state.")

    token_data = exchange_oauth_code(request, code)
    oauth_user = fetch_oauth_user(token_data["access_token"])
    session_token = generate_session_token()
    create_auth_session(session_token, oauth_user, session_expires_at())

    response = RedirectResponse(url="/")
    response.set_cookie(
        AUTH_COOKIE_NAME,
        session_token,
        httponly=True,
        secure=cookie_secure(request),
        samesite="lax",
        max_age=SESSION_MAX_AGE_SECONDS,
    )
    response.delete_cookie(STATE_COOKIE_NAME)
    return response


@router.post("/auth/logout")
def logout(request: Request):
    session_token = request.cookies.get(AUTH_COOKIE_NAME)

    if session_token:
        delete_auth_session(session_token)

    response = JSONResponse({"logged_out": True})
    response.delete_cookie(AUTH_COOKIE_NAME)
    return response
