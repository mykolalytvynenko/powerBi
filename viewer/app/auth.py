"""Вхід через Entra ID (OpenID Connect, authorization code flow з PKCE через MSAL)."""

from __future__ import annotations

from urllib.parse import urlencode

import msal
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .config import Settings

LOGIN_SCOPES = ["User.Read"]  # openid/profile MSAL додає сам


def _safe_next(value: str | None) -> str:
    # тільки локальні шляхи, щоб не було відкритого редиректу
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    def msal_app() -> msal.ConfidentialClientApplication:
        return msal.ConfidentialClientApplication(
            settings.client_id, authority=settings.authority, client_credential=settings.client_secret
        )

    @router.get("/login")
    def login(request: Request, next: str | None = None):
        if settings.auth_disabled:  # вхід вимкнено: сторінки відкриті, входити нікуди
            return RedirectResponse(_safe_next(next), status_code=303)
        flow = msal_app().initiate_auth_code_flow(LOGIN_SCOPES, redirect_uri=settings.redirect_uri)
        auth_uri = flow.pop("auth_uri")
        request.session["flow"] = flow
        request.session["next"] = _safe_next(next)
        return RedirectResponse(auth_uri, status_code=303)

    @router.get("/auth/callback")
    def callback(request: Request):
        flow = request.session.pop("flow", None)
        if not flow:
            return RedirectResponse("/login", status_code=303)
        try:
            result = msal_app().acquire_token_by_auth_code_flow(flow, dict(request.query_params))
        except ValueError:  # state не збігся, повторний або підроблений запит
            return RedirectResponse("/login", status_code=303)
        if "error" in result:
            request.session.clear()
            q = urlencode({"msg": result.get("error_description") or result["error"]})
            return RedirectResponse(f"/auth/error?{q}", status_code=303)
        claims = result.get("id_token_claims", {})
        request.session["user"] = {
            "name": claims.get("name", ""),
            "username": claims.get("preferred_username", ""),
            "oid": claims.get("oid", ""),
        }
        return RedirectResponse(request.session.pop("next", "/"), status_code=303)

    @router.get("/logout")
    def logout(request: Request):
        request.session.clear()
        if settings.auth_disabled:
            return RedirectResponse("/", status_code=303)
        q = urlencode({"post_logout_redirect_uri": settings.base_url + "/"})
        return RedirectResponse(f"{settings.authority}/oauth2/v2.0/logout?{q}", status_code=303)

    return router
