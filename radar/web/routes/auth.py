"""Auth routes."""

import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from radar.web import _requires_auth

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    """Login page."""
    requires, _ = _requires_auth()
    if not requires:
        return RedirectResponse(url="/", status_code=302)

    error = request.query_params.get("error")

    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Login - Radar</title>
            <link rel="stylesheet" href="/static/css/radar.css">
        </head>
        <body style="display: flex; align-items: center; justify-content: center; min-height: 100vh;">
            <div class="card" style="width: 100%; max-width: 400px;">
                <div class="card__header">
                    <span class="card__title">Radar Authentication</span>
                </div>
                <div class="card__body">
                    {f'<div class="text-error mb-md">{error}</div>' if error else ''}
                    <form method="POST" action="/login">
                        <label class="config-field__label">Auth Token</label>
                        <input type="password" name="token" class="input" placeholder="Enter auth token" autofocus>
                        <button type="submit" class="btn btn--primary mt-md" style="width: 100%;">Login</button>
                    </form>
                </div>
            </div>
        </body>
        </html>
        """,
        status_code=200,
    )


@router.post("/login")
async def login_post(request: Request):
    """Handle login form submission."""
    form = await request.form()
    token = form.get("token", "")

    requires, expected_token = _requires_auth()
    if not requires:
        return RedirectResponse(url="/", status_code=302)

    if expected_token and secrets.compare_digest(str(token), expected_token):
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key="radar_auth",
            value=token,
            httponly=True,
            max_age=86400 * 30,  # 30 days
            samesite="strict",
        )
        return response

    return RedirectResponse(url="/login?error=Invalid+token", status_code=302)


@router.get("/logout")
async def logout():
    """Logout and clear auth cookie."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("radar_auth")
    return response
