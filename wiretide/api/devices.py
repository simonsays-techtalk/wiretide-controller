from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from datetime import timezone, datetime
import json, enum, aiosqlite
from fastapi import Body
from fastapi.templating import Jinja2Templates

from wiretide.tokens import get_shared_token
from wiretide.db import DB_PATH
from wiretide.api.auth import require_login, require_api_token, rbac_required
from wiretide.models import DeviceStatus

from fastapi.responses import JSONResponse


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

@router.post("/status", dependencies=[Depends(require_api_token)])
async def accept_status(payload: dict = Body(...)):
    mac = (payload.get("mac") or "").lower()
    if not mac:
        return JSONResponse({"error": "missing mac"}, status_code=400)

    s = payload.get("settings") or {}

    def pick(*keys, default=None):
        for k in keys:
            if k in s and s[k] not in (None, ""):
                return s[k]
            if k in payload and payload[k] not in (None, ""):
                return payload[k]
        return default

    model       = pick("model", default="unknown")
    wan_ip      = pick("wan_ip", default=None)
    dns         = pick("dns", "dns_servers", default=[])
    ntp         = pick("ntp", "ntp_synced", default=False)
    fw_state    = pick("firewall", "firewall_state", default=True)
    fw_profile  = pick("firewall_profile", "firewall_profile_active", default=None)
    sec_raw     = pick("security_log_samples", default=[])
    ssh_enabled = bool(payload.get("ssh_enabled"))

    # Normalize DNS -> list[str]
    if isinstance(dns, str):
        try:
            maybe = json.loads(dns)
            dns_list = maybe if isinstance(maybe, list) else [dns]
        except Exception:
            dns_list = [x.strip() for x in dns.split(",") if x.strip()]
    elif isinstance(dns, list):
        dns_list = [str(x) for x in dns]
    else:
        dns_list = []

    # Normalize security logs -> list[str] (cap 50)
    if isinstance(sec_raw, list):
        sec_list = [str(x) for x in sec_raw][-50:]
    elif isinstance(sec_raw, str):
        sec_list = [ln for ln in sec_raw.splitlines() if ln.strip()][-50:]
    else:
        sec_list = []

    updated_at = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        # Upsert live status
        await db.execute(
            """
            INSERT INTO device_status (
                mac, model, wan_ip, dns_servers, ntp_synced, firewall_state,
                firewall_profile_active, security_log_samples, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mac) DO UPDATE SET
                model=excluded.model,
                wan_ip=excluded.wan_ip,
                dns_servers=excluded.dns_servers,
                ntp_synced=excluded.ntp_synced,
                firewall_state=excluded.firewall_state,
                firewall_profile_active=excluded.firewall_profile_active,
                security_log_samples=excluded.security_log_samples,
                updated_at=excluded.updated_at
            """,
            (
                mac,
                str(model) if model is not None else None,
                str(wan_ip) if wan_ip is not None else None,
                json.dumps(dns_list),
                1 if ntp else 0,
                str(fw_state) if fw_state is not None else None,
                str(fw_profile) if fw_profile is not None else None,
                json.dumps(sec_list),
                updated_at,
            ),
        )

        # 👉 Fix 2: update ook devices.last_seen (en ssh_enabled)
        await db.execute(
            "UPDATE devices SET last_seen = ?, ssh_enabled = ? WHERE mac = ?",
            (updated_at, 1 if ssh_enabled else 0, mac),
        )

        await db.commit()

    return {"status": "ok", "mac": mac, "events": len(sec_list), "profile": fw_profile}
    
@router.get("/config")
async def get_config(request: Request, _: str = Depends(require_api_token)):
    """Return queued package for an approved device (most-recent)."""
    mac = (request.headers.get("X-MAC") or "").lower().strip()
    if not mac:
        raise HTTPException(status_code=401, detail="Missing X-MAC")

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT approved FROM devices WHERE mac = ?", (mac,))
        row = await cur.fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=403, detail="Unauthorized or unapproved")

        
        cur = await db.execute(
            "SELECT config FROM device_configs WHERE mac = ? ORDER BY created_at DESC LIMIT 1",
            (mac,),
        )
        row = await cur.fetchone()

    if not row or not row[0]:
        return JSONResponse({"package": {}, "available": False, "sha256": None})

    try:
        cfg = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        pkg = cfg.get("package", {}) if isinstance(cfg, dict) else {}
        sha = cfg.get("sha256") if isinstance(cfg, dict) else None
        return JSONResponse({"package": pkg, "available": True, "sha256": sha})
    except Exception:
        return JSONResponse({"package": {}, "available": False, "sha256": None})

async def require_api_token(request: Request):
    token = request.headers.get("X-API-Token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing API token")

    token = token.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM config WHERE key = 'shared_token'")
        row = await cursor.fetchone()
        db_token = (row[0] if row else "").strip()
        if token != db_token:
            raise HTTPException(status_code=403, detail="Invalid API token")


@router.get("/api/devices")
async def list_devices(_: str = Depends(require_login)):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT
              d.hostname,
              d.mac,
              d.ip,
              COALESCE(ds.updated_at, d.last_seen) AS last_seen,
              d.status,
              d.ssh_enabled,
              d.device_type,
              d.approved
            FROM devices d
            LEFT JOIN device_status ds ON ds.mac = d.mac
            ORDER BY last_seen DESC
        """)
        rows = await cursor.fetchall()
    return JSONResponse(content=[
        {
            "hostname": row[0],
            "mac": row[1],
            "ip": row[2],
            "last_seen": row[3],  # ISO string uit DB; front-end formatLocalTime doet de rest
            "status": row[4],
            "ssh_enabled": bool(row[5]),
            "device_type": row[6],
            "approved": bool(row[7]),
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

    mac_norm = mac.lower()

    async with aiosqlite.connect(DB_PATH) as db:
        # Basis device-info
        cursor = await db.execute(
            "SELECT hostname, ip, ssh_enabled, device_type, agent_update_allowed FROM devices WHERE mac = ?", (mac_norm,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404)

        device = {
            "hostname": row[0],
            "ip": row[1],
            "ssh_enabled": bool(row[2]),
            "device_type": row[3],
            "mac": mac_norm,
            "agent_update_allowed": bool(row[4]),
        }

        # Live status + extra firewallvelden
        cursor = await db.execute(
            """
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
            """,
            (mac_norm,),
        )
        settings_row = await cursor.fetchone()

        settings = None
        if settings_row:
            # Robust parse for security_log_samples: JSON list OR newline-delimited text OR single string
            sec_samples = []
            raw_sec = settings_row[6]
            if raw_sec:
                try:
                    parsed = json.loads(raw_sec)
                    if isinstance(parsed, list):
                        sec_samples = [str(x) for x in parsed]
                    elif isinstance(parsed, str):
                        s = parsed.strip()
                        if s:
                            sec_samples = s.splitlines()
                except Exception:
                    # Not JSON – treat as plaintext blob
                    try:
                        sec_samples = [ln for ln in str(raw_sec).splitlines() if ln.strip()]
                    except Exception:
                        sec_samples = []

            # dns_servers may be JSON or CSV/plaintext; support both
            dns_field = settings_row[2]
            dns_list = []
            if dns_field:
                try:
                    dns_list = json.loads(dns_field)
                    if not isinstance(dns_list, list):
                        dns_list = [str(dns_field)]
                except Exception:
                    dns_list = [s.strip() for s in str(dns_field).split(',') if s.strip()]

            settings = {
                "model": settings_row[0],
                "wan_ip": settings_row[1],
                "dns": dns_list,
                "ntp_synced": settings_row[3],
                "firewall_state": settings_row[4],
                "firewall_profile_active": settings_row[5],
                "security_log_samples": sec_samples,
                "updated_at": settings_row[7],
            }

        # Nieuw: defaults voor de UI uit de laatst gequeue'de config
        ui_defaults = {
            "firewall_profile_requested": None,
            "sec_enabled": False,
            "sec_level": "info",
            "sec_prefix": "WTSEC",
        }
        cursor = await db.execute(
            "SELECT config FROM device_configs WHERE mac = ? ORDER BY created_at DESC LIMIT 1",
            (mac_norm,),
        )
        row = await cursor.fetchone()
        if row and row[0]:
            try:
                cfg = json.loads(row[0])  # {"package": {...}, "sha256": "..."}
                pkg = (cfg.get("package") or {})
                sl = pkg.get("security_logging") or {}
                ui_defaults = {
                    "firewall_profile_requested": pkg.get("firewall_profile"),
                    "sec_enabled": bool(sl.get("enabled", False)),
                    "sec_level": sl.get("level", "info"),
                    "sec_prefix": sl.get("prefix", "WTSEC"),
                }
            except Exception:
                pass

    return templates.TemplateResponse(
        f"{device_type}.html",
        {
            "request": request,
            "device": device,
            "settings": settings,
            "ui_defaults": ui_defaults,
        },
    )
    
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

