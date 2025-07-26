# wiretide/api/logs.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
import os, re

from wiretide.api.auth import require_login

LOG_FILE = "/var/log/wiretide.log"

router = APIRouter()

@router.get("/api/logs")
async def get_logs(level: str = "ALL", _: str = Depends(require_login)):
    """Return the last 200 log lines, optionally filtered by level."""
    level = level.upper()
    valid_levels = {"ALL", "INFO", "WARNING", "ERROR"}
    if level not in valid_levels:
        raise HTTPException(status_code=400, detail="Invalid log level")

    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {"lines": ["Log file not found."]}

    # Keep last 200 lines
    lines = lines[-200:]

    # Filter by level if needed
    if level != "ALL":
        regex = re.compile(rf"\b{level}\b")
        lines = [line for line in lines if regex.search(line)]
    return {"lines": lines}


@router.get("/api/logs/download")
async def download_logs(_: str = Depends(require_login)):
    """Download the raw Wiretide log file."""
    try:
        return FileResponse(LOG_FILE, filename="wiretide.log")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Log file not found")
