from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from datetime import timezone, datetime
import json, enum, aiosqlite
from fastapi.templating import Jinja2Templates

from wiretide.tokens import get_shared_token
from wiretide.db import DB_PATH
from wiretide.api.auth import require_login, require_api_token, rbac_required
from wiretide.models import DeviceStatus

templates = Jinja2Templates(directory="wiretide/templates")
router = APIRouter()

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

@router.post("/register")
async def register_device(device: DeviceRegistration, request: Request):
    ip = request.client.host
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, status FROM devices WHERE mac = ?", (device.mac,)) as cursor:
            existing = await cursor.fetchone()
        if existing:
            device_id, current_status = existing
            new_status = 'waiting' if current_status == 'removed' else current_status
            await db.execute(
                "UPDATE devices SET hostname = ?, ip = ?, last_seen = ?, status = ? WHERE id = ?",
                (device.hostname, ip, datetime.now(), new_status, device_id)
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
    now = datetime.now()
    mac_lower = status.mac.lower()

    async with aiosqlite.connect(DB_PATH) as db:
        # devices
        await db.execute("""
            UPDATE devices
            SET ip = ?, ssh_enabled = ?, last_seen = ?, hostname = ?, status_json = ?
            WHERE mac = ? AND status != 'removed'
        """, (
            client_ip,
            status.ssh_enabled,
            now,
            status.hostname,
            json.dumps(status.dict()),
            mac_lower
        ))

        if status.settings:
            model = status.settings.get("model")
            wan_ip = status.settings.get("wan_ip") or status.settings.get("device_ip") or ""
            dns = status.settings.get("dns") or []
            ntp_synced = bool(status.settings.get("ntp"))
            fw_state = "enabled" if status.settings.get("firewall") else "disabled"
            fw_profile = status.settings.get("firewall_profile")

            # --- robust maken: forceer lijst ---
            raw_sec = status.settings.get("security_log_samples", [])
            sec_samples: list[str] = []
            if isinstance(raw_sec, list):
                sec_samples = [str(x) for x in raw_sec]
            elif isinstance(raw_sec, str):
                # probeer te parsen als JSON; anders leeg
                try:
                    parsed = json.loads(raw_sec)
                    if isinstance(parsed, list):
                        sec_samples = [str(x) for x in parsed]
                except Exception:
                    sec_samples = []
            # alles wat geen lijst is -> lege lijst

            await db.execute("""
                INSERT INTO device_status (
                    mac, model, wan_ip, dns_servers, ntp_synced, firewall_state,
                    firewall_profile_active, security_log_samples, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mac) DO UPDATE SET
                  model = excluded.model,
                  wan_ip = excluded.wan_ip,
                  dns_servers = excluded.dns_servers,
                  ntp_synced = excluded.ntp_synced,
                  firewall_state = excluded.firewall_state,
                  firewall_profile_active = excluded.firewall_profile_active,
                  security_log_samples = excluded.security_log_samples,
                  updated_at = excluded.updated_at
            """, (
                mac_lower,
                model,
                wan_ip,
                json.dumps(dns),
                ntp_synced,
                fw_state,
                fw_profile,
                json.dumps(sec_samples),
                now
            ))
        await db.commit()

@router.get("/config")
async def get_config(request: Request, _: str = Depends(require_api_token)):
    mac = request.headers.get("X-MAC", "").lower()
    if not mac:
        raise HTTPException(status_code=401)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT approved FROM devices WHERE mac = ?", (mac,))
        row = await cursor.fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=403, detail="Unauthorized or unapproved")
        cursor = await db.execute("SELECT config FROM device_configs WHERE mac = ?", (mac,))
        row = await cursor.fetchone()
        if not row:
            return JSONResponse({"package": {}, "available": False})
        try:
            config_data = json.loads(row[0])
            return JSONResponse({
                "package": config_data.get("package", {}),
                "sha256": config_data.get("sha256", ""),
                "available": True
            })
        except Exception:
            return JSONResponse({"package": {}, "available": False})

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
            "last_seen": (datetime.fromisoformat(row[3]).astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if row[3] else None),
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

    mac_norm = mac.lower()  # ✅ normalize

    async with aiosqlite.connect(DB_PATH) as db:
        # Basis device-info
        cursor = await db.execute(
            "SELECT hostname, ip, ssh_enabled, device_type FROM devices WHERE mac = ?", (mac_norm,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404)

        device = {
            "hostname": row[0],
            "ip": row[1],
            "ssh_enabled": bool(row[2]),
            "device_type": row[3],
            "mac": mac_norm,  # ✅ voorkom nieuwe mismatches in links/UI
        }

        # Live status + extra firewallvelden
        cursor = await db.execute("""
            SELECT
              model,
              wan_ip,
              dns_servers,
              ntp_synced,
              firewall_state,
              firewall_profile_active,
              security_log_samples,
              updated_at
            FROM device_status
            WHERE mac = ?
        """, (mac_norm,))
        settings_row = await cursor.fetchone()

        settings = None
        if settings_row:
            sec_samples = []
            if settings_row[6]:
                try:
                    parsed = json.loads(settings_row[6])
                    if isinstance(parsed, list):
                        sec_samples = [str(x) for x in parsed]
                except Exception:
                    sec_samples = []

            settings = {
                "model": settings_row[0],
                "wan_ip": settings_row[1],
                "dns": json.loads(settings_row[2]) if settings_row[2] else [],
                "ntp_synced": settings_row[3],
                "firewall_state": settings_row[4],
                "firewall_profile_active": settings_row[5],
                "security_log_samples": sec_samples,
                "updated_at": settings_row[7],
            }

    return templates.TemplateResponse(f"{device_type}.html", {
        "request": request,
        "device": device,
        "settings": settings
    })


@router.post("/api/queue-config")
async def queue_config(
    mac: str = Form(...),
    package_json: str = Form(...),
    sha256: str = Form(...),
    _: str = Depends(require_login)
):
    import hashlib
    try:
        package = json.loads(package_json)
    except Exception:
        raise HTTPException(400, detail="Invalid JSON in package")

    calculated = hashlib.sha256(
        json.dumps(package, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    if calculated != sha256:
        raise HTTPException(400, detail="SHA256 mismatch")

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT approved FROM devices WHERE mac = ?", (mac,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, detail="Device not found")
        if not row[0]:
            raise HTTPException(403, detail="Device not approved")

        config_blob = json.dumps({"package": package, "sha256": sha256})
        await db.execute("""
            INSERT INTO device_configs (mac, config, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(mac) DO UPDATE
            SET config=excluded.config, created_at=excluded.created_at
        """, (mac, config_blob, datetime.now()))
        await db.commit()

    return {"status": "queued", "keys": list(package.keys())}

@router.get("/token/{mac}")
async def get_device_token(mac: str, request: Request):
    token = await get_shared_token()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT approved FROM devices WHERE mac = ?", (mac,))
        row = await cursor.fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=403, detail="Device not approved")
    return {"token": token}

@router.get("/config/agent", dependencies=[Depends(require_api_token)])
async def get_agent_update_config(request: Request):
    mac = request.headers.get("X-MAC", "").lower()
    if not mac:
        raise HTTPException(status_code=401)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT agent_update_allowed FROM devices WHERE mac = ?", (mac,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Device not found")
        per_device_allowed = bool(row[0])

    # deze helpers bestaan al in je codebase
    from wiretide.api.settings import get_config_value  # import binnen functie om circulars te vermijden
    updates_enabled = await get_config_value("agent_updates_enabled", "false") == "true"
    update_url = await get_config_value("agent_update_url", "")
    min_supported_version = await get_config_value("min_supported_agent_version", "0.1.0")

    allow_update = updates_enabled or per_device_allowed
    return {
        "update_available": allow_update,
        "update_url": update_url if allow_update else None,
        "min_supported_version": min_supported_version
    }

@router.post("/devices/{mac}/agent-update", dependencies=[rbac_required("devices:manage")])
async def toggle_agent_update(mac: str, request: Request):
    form = await request.form()
    enabled = form.get("enabled", "false").lower() == "true"

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM devices WHERE mac = ?", (mac,))
        if (await cursor.fetchone())[0] == 0:
            raise HTTPException(status_code=404, detail="Device not found")
        await db.execute("UPDATE devices SET agent_update_allowed = ? WHERE mac = ?", (int(enabled), mac))
        await db.commit()

    return {"status": "ok", "enabled": enabled}

