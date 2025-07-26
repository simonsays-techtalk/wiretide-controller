import aiosqlite
import json
import ipaddress
from fastapi import APIRouter, Depends
from wiretide.api.auth import require_login
from wiretide.db import DB_PATH

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
    devices = await get_devices()
    combined_clients = {}

    # Track Wiretide device MACs so we don't list them as clients
    wiretide_macs = {d["mac"] for d in devices}

    for device in devices:
        status = device.get("status") or {}
        for c in status.get("clients", []):
            mac = (c.get("mac") or "").lower()
            if not mac or mac == "0/0/0":
                continue
            if mac in wiretide_macs:
                continue  # Don't list Wiretide devices as clients

            ip = c.get("ip")
            if ip and not ip.startswith("192.168.188."):
                ip = None  # Drop WAN/external IPs

            hostname = c.get("hostname") if c.get("hostname") and c.get("hostname") != "unknown" else None
            conn_type = "wifi" if c.get("connected_via") == "wifi" else "ethernet"

            if mac not in combined_clients:
                combined_clients[mac] = {
                    "mac": mac,
                    "ip": ip,
                    "hostname": hostname,
                    "type": conn_type,
                    "connected_to": device["hostname"],
                    "connected_mac": device["mac"],
                    "device_type": device["device_type"] or "unknown"
                }
            else:
                existing = combined_clients[mac]
                # Prefer Wi‑Fi type if seen via AP
                if conn_type == "wifi":
                    existing["type"] = "wifi"
                    existing["connected_to"] = device["hostname"]
                    existing["connected_mac"] = device["mac"]
                    existing["device_type"] = device["device_type"] or "unknown"
                # Fill missing IP/hostname if available
                if not existing["ip"] and ip:
                    existing["ip"] = ip
                if not existing["hostname"] and hostname:
                    existing["hostname"] = hostname

    # Sort: Wi‑Fi first, then Ethernet, alphabetically by hostname or MAC
    sorted_clients = sorted(
        combined_clients.values(),
        key=lambda c: (
            0 if c["type"] == "wifi" else 1,
            (c["hostname"] or c["mac"]).lower()
        )
    )
    return sorted_clients

@router.get("/clients", dependencies=[Depends(require_login)])
async def list_clients():
    return await get_clients_list()
