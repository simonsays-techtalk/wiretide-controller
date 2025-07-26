from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from datetime import datetime
import aiosqlite
import json
import enum
from wiretide.tokens import get_shared_token
from wiretide.db import DB_PATH
from wiretide.api.auth import require_login
from fastapi.templating import Jinja2Templates
from wiretide.models import DeviceStatus
from wiretide.api.auth import require_login, require_api_token
from fastapi import Depends

templates = Jinja2Templates(directory="wiretide/templates")

router = APIRouter()

# --- Models ---
class DeviceRegistration(BaseModel):
    hostname: str
    mac: str
    ssh_fingerprint: str
    ssh_enabled: bool

class DeviceType(str, enum.Enum):
    unknown = "unknown"
    router = "router"
    switch = "switch"
    firewall = "firewall"
    access_point = "access_point"

# --- Endpoints ---

@router.post("/register")
async def register_device(device: DeviceRegistration, request: Request, _: str = Depends(require_api_token)):
    ip = request.client.host
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, status FROM devices WHERE mac = ?", (device.mac,)) as cursor:
            existing = await cursor.fetchone()

        if existing:
            device_id, current_status = existing
            new_status = 'waiting' if current_status == 'removed' else current_status
            await db.execute(
                "UPDATE devices SET ip = ?, last_seen = ?, status = ? WHERE id = ?",
                (ip, datetime.utcnow(), new_status, device_id)
            )
        else:
            await db.execute(
                "INSERT INTO devices (hostname, ip, mac, ssh_fingerprint, ssh_enabled, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (device.hostname, ip, device.mac, device.ssh_fingerprint, device.ssh_enabled, 'waiting')
            )
        await db.commit()
    return {"status": "ok"}

@router.post("/status")
async def device_status(status: DeviceStatus, request: Request, _: str = Depends(require_api_token)):
    client_ip = request.client.host
    now = datetime.utcnow().isoformat()

    mac_lower = status.mac.lower()

    async with aiosqlite.connect(DB_PATH) as db:
        # Store full payload (including clients) in status_json
        await db.execute("""
            UPDATE devices
            SET ip = ?, ssh_enabled = ?, last_seen = ?, status_json = ?
            WHERE mac = ? AND status != 'removed'
        """, (client_ip, status.ssh_enabled, now, json.dumps(status.dict()), mac_lower))

        # Update summary in device_status (quick lookups)
        if status.settings:
            model = status.settings.get("model")
            wan_ip = status.settings.get("wan_ip")
            dns = status.settings.get("dns") or []
            ntp_synced = bool(status.settings.get("ntp"))
            firewall_state = "enabled" if status.settings.get("firewall") else "disabled"

            await db.execute("""
                INSERT INTO device_status (mac, model, wan_ip, dns_servers, ntp_synced, firewall_state, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mac) DO UPDATE SET
                  model = excluded.model,
                  wan_ip = excluded.wan_ip,
                  dns_servers = excluded.dns_servers,
                  ntp_synced = excluded.ntp_synced,
                  firewall_state = excluded.firewall_state,
                  updated_at = excluded.updated_at
            """, (
                mac_lower, model, wan_ip, json.dumps(dns),
                ntp_synced, firewall_state, now
            ))
        await db.commit()

@router.get("/config")
async def get_config(request: Request):
    auth = request.headers.get("Authorization", "")
    mac = request.headers.get("X-MAC", "").lower()

    if not auth.startswith("Bearer ") or not mac:
        raise HTTPException(401)

    token = auth.removeprefix("Bearer ").strip()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT approved FROM devices WHERE mac = ? AND token = ?", (mac, token))
        row = await cursor.fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=403, detail="Unauthorized or unapproved")

        cursor = await db.execute("SELECT config FROM device_configs WHERE mac = ?", (mac,))
        row = await cursor.fetchone()
        if not row:
            return JSONResponse({"config": {}, "available": False})

        return JSONResponse({"config": json.loads(row[0]), "available": True})


@router.get("/api/devices")
async def list_devices(_: str = Depends(require_login)):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT hostname, mac, ip, last_seen, status, ssh_enabled, device_type, approved
            FROM devices ORDER BY last_seen DESC
        """)
        rows = await cursor.fetchall()
    return JSONResponse(content=[
        {
            "hostname": row[0],
            "mac": row[1],
            "ip": row[2],
            "last_seen": row[3],
            "status": row[4],
            "ssh_enabled": bool(row[5]),
            "device_type": row[6],
            "approved": bool(row[7])
        } for row in rows
    ])


@router.post("/api/approve")
async def approve_device(mac: str = Form(...), device_type: str = Form(...), _: str = Depends(require_login)):
    if device_type not in [t.value for t in DeviceType if t != DeviceType.unknown]:
        raise HTTPException(status_code=400, detail="Invalid or missing device type.")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE devices SET approved = 1, status = 'approved', device_type = ? WHERE mac = ?",
            (device_type, mac)
        )
        await db.commit()
    return {"status": "approved"}


@router.post("/api/deny")
async def deny_device(mac: str = Form(...), _: str = Depends(require_login)):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE devices SET status = 'denied' WHERE mac = ?", (mac,))
        await db.commit()
    return {"status": "denied"}


@router.post("/api/block")
async def block_device(mac: str = Form(...), _: str = Depends(require_login)):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE devices SET status = 'blocked' WHERE mac = ?", (mac,))
        await db.commit()
    return {"status": "blocked"}


@router.post("/api/remove")
async def remove_device(mac: str = Form(...), _: str = Depends(require_login)):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE devices SET status = 'removed' WHERE mac = ?", (mac,))
        await db.commit()
    return {"status": "removed"}


@router.get("/clients/{device_type}/{mac}", response_class=HTMLResponse)
async def device_page(device_type: str, mac: str, request: Request, _: str = Depends(require_login)):
    if device_type not in [t.value for t in DeviceType if t != DeviceType.unknown]:
        raise HTTPException(status_code=404)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT hostname, ip, ssh_enabled, device_type FROM devices WHERE mac = ?", (mac,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404)

        device = {
            "hostname": row[0],
            "ip": row[1],
            "ssh_enabled": bool(row[2]),
            "device_type": row[3],
            "mac": mac
        }

        cursor = await db.execute("""
            SELECT model, wan_ip, dns_servers, ntp_synced, firewall_state, updated_at
            FROM device_status WHERE mac = ?
        """, (mac,))
        settings_row = await cursor.fetchone()
        settings = None
        if settings_row:
            settings = {
                "model": settings_row[0],
                "wan_ip": settings_row[1],
                "dns": json.loads(settings_row[2]) if settings_row[2] else [],
                "ntp_synced": settings_row[3],
                "firewall_state": settings_row[4],
                "updated_at": settings_row[5]
            }

    return templates.TemplateResponse(f"{device_type}.html", {
        "request": request,
        "device": device,
        "settings": settings
    })


@router.post("/api/queue-config")
async def queue_config(mac: str = Form(...), config_json: str = Form(...), _: str = Depends(require_login)):
    try:
        parsed = json.loads(config_json)
    except Exception:
        raise HTTPException(400, detail="Invalid JSON")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO device_configs (mac, config, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(mac) DO UPDATE SET config=excluded.config, created_at=excluded.created_at
        """, (mac, json.dumps(parsed), datetime.utcnow().isoformat()))
        await db.commit()
    return {"status": "queued"}


@router.get("/token/{mac}")
async def get_device_token(mac: str, request: Request):
    token = await get_shared_token()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT approved FROM devices WHERE mac = ?", (mac,))
        row = await cursor.fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=403, detail="Device not approved")
    return {"token": token}
