import aiosqlite
import json
import ipaddress
from fastapi import APIRouter, Depends
from wiretide.api.auth import rbac_required
from wiretide.db import DB_PATH
from wiretide.db import get_db

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


@router.get("/clients", dependencies=[rbac_required("devices:view")])
async def list_clients():
    """Return the current list of connected clients (read-only)."""
    return await get_clients_list()

