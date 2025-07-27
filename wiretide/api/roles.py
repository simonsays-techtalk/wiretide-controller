# wiretide/api/roles.py
from fastapi import APIRouter, Depends, HTTPException, Form, Path
import aiosqlite
from wiretide.db import DB_PATH
from wiretide.api.auth import rbac_required

router = APIRouter(prefix="/api/roles")

# --- Get all roles and their permissions ---
@router.get("/", dependencies=[rbac_required("roles:manage")])
async def list_roles():
    """Return all roles with their permissions."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Get all roles
        cursor = await db.execute("SELECT id, name FROM roles")
        roles = [{"id": row[0], "name": row[1], "permissions": []} for row in await cursor.fetchall()]

        # Map role_id -> permissions
        cursor = await db.execute("SELECT role_id, permission FROM role_permissions")
        for row in await cursor.fetchall():
            for r in roles:
                if r["id"] == row[0]:
                    r["permissions"].append(row[1])
    return {"roles": roles}


# --- Get all available permissions (for the UI) ---
@router.get("/permissions", dependencies=[rbac_required("roles:manage")])
async def list_permissions():
    """Return a static list of all known permissions (for building the UI)."""
    # Expandable list - add new ones here as the app grows
    permissions = [
        "system:view", "system:restart",
        "cert:regenerate",
        "logs:view", "logs:download",
        "devices:view", "devices:approve", "devices:manage",
        "backup:download", "backup:restore", "system:reset",
        "users:create", "users:delete",
        "token:regenerate"
    ]
    return {"permissions": permissions}


# --- Update a role's permissions ---
@router.post("/{role_id}/permissions", dependencies=[rbac_required("roles:manage")])
async def update_role_permissions(
    role_id: int = Path(...),
    permissions: str = Form(...)
):
    """
    Update permissions for a role.
    - `permissions` is a comma-separated string from the form.
    """
    perms = [p.strip() for p in permissions.split(",") if p.strip()]

    async with aiosqlite.connect(DB_PATH) as db:
        # Ensure the role exists
        cursor = await db.execute("SELECT id FROM roles WHERE id = ?", (role_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Role not found")

        # Clear old permissions
        await db.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))

        # Insert new permissions
        for perm in perms:
            await db.execute(
                "INSERT OR IGNORE INTO role_permissions (role_id, permission) VALUES (?, ?)",
                (role_id, perm)
            )
        await db.commit()

    return {"status": "updated", "role_id": role_id, "permissions": perms}

