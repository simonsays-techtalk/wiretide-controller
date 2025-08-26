import aiosqlite
import json
import ipaddress
from fastapi import APIRouter, Depends
from wiretide.api.auth import rbac_required
from wiretide.db import DB_PATH
from wiretide.db import get_db
from wiretide.api.auth import require_login
from fastapi import Form
from datetime import datetime
import hashlib


router = APIRouter(prefix="/api")

async def get_devices():
    devices = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT hostname, mac, device_type, last_seen, status_json FROM devices") as cur:
            async for row in cur:
                try:
                    status = json.loads(row["status_json"]) if row["status_json"] else {}
                except json.JSONDecodeError:
                    status = {}
                devices.append({
                    "hostname": row["hostname"],
                    "mac": row["mac"].lower(),
                    "device_type": row["device_type"],
                    "last_seen": row["last_seen"],
                    "status": status
                })
    return devices

async def get_clients_list():
    query = """
        SELECT ds.mac, d.hostname, ds.clients, ds.updated_at
        FROM device_status ds
        LEFT JOIN devices d ON ds.mac = d.mac
        WHERE ds.clients IS NOT NULL
        ORDER BY ds.updated_at DESC
    """
    results = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query) as cursor:
            async for row in cursor:
                mac, hostname, clients_json, updated_at = row
                try:
                    clients = json.loads(clients_json)
                    for client in clients:
                        client["block_inet"] = await is_blocked(client.get("mac", "").lower())
                except Exception:
                    clients = []
                results.append({
                    "mac": mac,
                    "hostname": hostname or "(unknown)",
                    "client_count": len(clients),
                    "clients": clients,
                    "updated_at": updated_at,
                })
    return results
    
async def is_blocked(client_mac: str) -> bool:
    client_mac = client_mac.lower()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT block_internet FROM client_controls WHERE client_mac = ?", (client_mac,))
        row = await cur.fetchone()
        return bool(row and row[0])


@router.get("/clients", dependencies=[rbac_required("devices:view")])
async def list_clients():
    """Return the current list of connected clients (read-only)."""
    return await get_clients_list()

@router.post("/clients/block-toggle", dependencies=[Depends(require_login)])
async def toggle_block(
    router_mac: str = Form(...),
    client_mac: str = Form(...),
    enabled: bool = Form(...)
):
    router_mac = router_mac.lower()
    client_mac = client_mac.lower()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO client_controls (client_mac, block_internet)
            VALUES (?, ?)
            ON CONFLICT(client_mac) DO UPDATE SET block_internet=excluded.block_internet
        """, (client_mac, int(enabled)))
        await db.commit()

    # Package klaarzetten voor agent
    from wiretide.api.devices import queue_config
    package = {
        "client_controls": [
            { "mac": client_mac, "block_internet": bool(enabled) }
        ]
    }
    sha = hashlib.sha256(
        json.dumps(package, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()

    # Zelfde DB-write als queue_config doet
    async with aiosqlite.connect(DB_PATH) as db:
        blob = json.dumps({"package": package, "sha256": sha})
        await db.execute("""
            INSERT INTO device_configs (mac, config, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(mac) DO UPDATE SET config=excluded.config, created_at=excluded.created_at
        """, (router_mac, blob, datetime.now()))
        await db.commit()

    return {"status": "ok", "client_mac": client_mac, "block": enabled}

