# wiretide/api/settings.py
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
import aiosqlite
from datetime import timedelta

from wiretide.api.auth import require_login, rbac_required
from wiretide.tokens import ensure_valid_shared_token, update_token
from wiretide.db import DB_PATH

templates = Jinja2Templates(directory="wiretide/templates")
router = APIRouter()

@router.get("/settings", dependencies=[Depends(require_login)])
async def settings_page(request: Request):
    """Render the settings page, showing the shared token and expiry."""
    token = await ensure_valid_shared_token()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM config WHERE key = 'shared_token_expiry'")
        expiry_row = await cursor.fetchone()
        expiry = expiry_row[0] if expiry_row else "Unknown"
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "token": token,
        "expiry": expiry
    })

@router.post("/settings/token", dependencies=[rbac_required("token:regenerate")])
async def handle_token_form(
    request: Request,
    expiry_hours: int = Form(...),
    action: str = Form(...)
):
    """Regenerate the shared token if requested. Restricted by RBAC."""
    if action == "regenerate":
        expiry_delta = timedelta(hours=expiry_hours)
        await update_token(expiry_delta)
    return RedirectResponse(url="/settings", status_code=303)

