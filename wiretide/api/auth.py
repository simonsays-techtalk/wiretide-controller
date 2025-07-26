import aiosqlite
from fastapi import HTTPException, Request
from wiretide.db import DB_PATH
from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from passlib.hash import bcrypt
import aiosqlite

from wiretide.db import DB_PATH

router = APIRouter()

# --- Token verification ---
async def require_api_token(request: Request):
    """Validate token for device API endpoints (/register, /status)."""
    token = request.headers.get("X-API-Token")
    if not token:
        # Backward compatibility with Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):].strip()

    if not token:
        raise HTTPException(status_code=400, detail="Missing API token")

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT token FROM tokens WHERE token = ?", (token,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=403, detail="Invalid API token")
            
# --- Token verification ---
async def verify_api_token(request: Request):
    """Verify API token from X-API-Token header for device endpoints."""
    token = request.headers.get("X-API-Token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing API token")

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT token FROM tokens WHERE token = ?", (token,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=403, detail="Invalid API token")



# --- Helper for other modules ---
def require_login(request: Request):
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Login required")


# --- Authentication & Session Routes ---

@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="wiretide/templates")
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    # NOTE: We aren't verifying passwords yet (need DB hashes)
    # For now, just set session.
    request.session["user"] = username
    return RedirectResponse("/index.html", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# --- Change Password ---
@router.get("/change-password", response_class=HTMLResponse)
async def change_password_form(request: Request):
    if "user" not in request.session:
        raise HTTPException(status_code=401)
    username = request.session.get("user")

    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="wiretide/templates")
    return templates.TemplateResponse("change_password.html", {
        "request": request,
        "username": username
    })


@router.post("/change-password")
async def change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    username = request.session.get("user")
    if not username:
        raise HTTPException(status_code=401)

    if new_password != confirm_password:
        from fastapi.templating import Jinja2Templates
        templates = Jinja2Templates(directory="wiretide/templates")
        return templates.TemplateResponse("change_password.html", {
            "request": request,
            "username": username,
            "error": "New passwords do not match."
        }, status_code=400)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        if not row or not bcrypt.verify(old_password, row[0]):
            from fastapi.templating import Jinja2Templates
            templates = Jinja2Templates(directory="wiretide/templates")
            return templates.TemplateResponse("change_password.html", {
                "request": request,
                "username": username,
                "error": "Invalid current password."
            }, status_code=403)

        new_hash = bcrypt.hash(new_password)
        await db.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hash, username))
        await db.commit()

    return RedirectResponse("/settings", status_code=303)


# --- User Management API ---

@router.get("/api/users")
async def list_users(_: str = Depends(require_login)):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT username, role FROM users")
        rows = await cursor.fetchall()
    return [{"username": row[0], "role": row[1]} for row in rows]


@router.post("/api/users")
async def create_user(
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    _: str = Depends(require_login)
):
    if role not in ["admin", "user"]:
        raise HTTPException(400, detail="Invalid role")

    password_hash = bcrypt.hash(password)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role)
        )
        await db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/api/users/delete")
async def delete_user(
    username: str = Form(...),
    request: Request = None,
    _: str = Depends(require_login)
):
    if username == request.session.get("user"):
        raise HTTPException(400, detail="You cannot delete your own account.")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE username = ?", (username,))
        await db.commit()
    return RedirectResponse("/settings", status_code=303)
