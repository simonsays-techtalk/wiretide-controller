import aiosqlite
from fastapi import HTTPException, Request, Form, APIRouter, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from passlib.hash import bcrypt
from wiretide.db import DB_PATH

router = APIRouter()

# --- Token verification ---
async def require_api_token(request: Request):
    token = request.headers.get("X-API-Token")
    if not token:
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


async def verify_api_token(request: Request):
    token = request.headers.get("X-API-Token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing API token")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT token FROM tokens WHERE token = ?", (token,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=403, detail="Invalid API token")


# --- Session & RBAC Helpers ---
def require_login(request: Request):
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Login required")


async def user_permissions(username: str):
    """Fetch all permissions for a given user."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT rp.permission FROM users u
            JOIN roles r ON u.role_id = r.id
            JOIN role_permissions rp ON rp.role_id = r.id
            WHERE u.username = ?
        """, (username,))
        rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def require_permission(request: Request, permission: str):
    """Low-level checker for a specific permission."""
    username = request.session.get("user")
    if not username:
        raise HTTPException(status_code=401, detail="Login required")

    # Confirm the user still exists
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE username = ?", (username,))
        exists = await cursor.fetchone()
    if not exists or exists[0] == 0:
        raise HTTPException(status_code=401, detail="User no longer exists")

    perms = await user_permissions(username)
    if "*" not in perms and permission not in perms:
        raise HTTPException(status_code=403, detail="Permission denied")


def rbac_required(permission: str = None):
    """Dependency to protect endpoints. Auto-infers permission from URL if not given."""
    async def checker(request: Request):
        inferred = permission
        if not inferred:
            # Convert /api/users/delete -> users:delete
            inferred = request.url.path.strip("/").replace("/", ":")
        await require_permission(request, inferred)
    return Depends(checker)


# --- Authentication Routes ---
@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="wiretide/templates")
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="wiretide/templates")

    # Verify credentials against DB
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()

    if not row or not bcrypt.verify(password, row[0]):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid username or password."
        }, status_code=401)

    # Set session only if user is valid
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
@router.get("/api/users", dependencies=[Depends(require_login)])
async def list_users():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT username, role FROM users")
        rows = await cursor.fetchall()
    return [{"username": row[0], "role": row[1]} for row in rows]


@router.post("/api/users", dependencies=[rbac_required("users:create")])
async def create_user(username: str = Form(...), password: str = Form(...), role: str = Form(...)):
    if role not in ["admin", "user"]:
        raise HTTPException(400, detail="Invalid role")

    password_hash = bcrypt.hash(password)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM roles WHERE name=?", (role,))
        row = await cursor.fetchone()
        role_id = row[0] if row else None
        await db.execute(
            "INSERT INTO users (username, password_hash, role, role_id) VALUES (?, ?, ?, ?)",
            (username, password_hash, role, role_id)
        )
        await db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/api/users/delete", dependencies=[rbac_required("users:delete")])
async def delete_user(username: str = Form(...), request: Request = None):
    if username == "admin":
        raise HTTPException(403, detail="Default admin cannot be deleted")
    if username == request.session.get("user"):
        raise HTTPException(400, detail="You cannot delete your own account.")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE username = ?", (username,))
        await db.commit()
    return RedirectResponse("/settings", status_code=303)

