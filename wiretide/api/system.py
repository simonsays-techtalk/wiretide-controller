from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
import os, re, subprocess, socket, hashlib
from wiretide.api.auth import require_login


LOG_FILE = "/var/log/wiretide.log"
CERT_DIR = "wiretide/certs"

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

    lines = lines[-200:]
    if level != "ALL":
        regex = re.compile(rf"\b{level}\b")
        lines = [line for line in lines if regex.search(line)]
    return {"lines": lines}


@router.get("/api/logs/download")
async def download_logs(_: str = Depends(require_login)):
    """Download the raw log file."""
    try:
        return FileResponse(LOG_FILE, filename="wiretide.log")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Log file not found")


@router.get("/api/system-info")
async def system_info(_: str = Depends(require_login)):
    """Basic controller info (hostname, uptime, version, certs, agent checksum)."""
    hostname = socket.gethostname()
    try:
        ip = socket.gethostbyname(hostname)
    except:
        ip = "unknown"

    # Uptime (Linux-specific)
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.readline().split()[0])
            uptime = f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"
    except:
        uptime = "unknown"

    # Version info
    version = "Wiretide v0.1.0"

    # Certificate details
    cert_path = os.path.join(CERT_DIR, "wiretide-ca.crt")
    if os.path.exists(cert_path):
        try:
            output = subprocess.check_output(
                ["openssl", "x509", "-enddate", "-noout", "-in", cert_path],
                universal_newlines=True
            ).strip()
            expiry = output.replace("notAfter=", "")
            cert_type = "Self-Signed"
        except Exception:
            expiry = "unknown"
            cert_type = "Self-Signed (unreadable)"
    else:
        expiry = "not found"
        cert_type = "Missing"

    # Agent checksum
    agent_path = "wiretide/static/wiretide-agent"
    if os.path.exists(agent_path):
        with open(agent_path, "rb") as f:
            checksum = hashlib.sha256(f.read()).hexdigest()
    else:
        checksum = "not found"

    return JSONResponse({
        "hostname": hostname,
        "ip": ip,
        "uptime": uptime,
        "version": version,
        "cert_type": cert_type,
        "cert_expiry": expiry,
        "agent_version": "1.0.0",
        "agent_checksum": checksum
    })


@router.post("/api/restart")
async def restart_controller(_: str = Depends(require_login)):
    """Restart the Wiretide systemd service."""
    try:
        subprocess.Popen(["systemctl", "restart", "wiretide.service"])
    except Exception as e:
        print("Restart failed:", e)
        raise HTTPException(status_code=500, detail="Failed to restart Wiretide.")
    return RedirectResponse("/settings", status_code=303)


@router.post("/api/cert/regenerate")
async def regenerate_cert(_: str = Depends(require_login)):
    """Regenerate the CA certificate."""
    cert_path = os.path.join(CERT_DIR, "wiretide-ca.crt")
    key_path = os.path.join(CERT_DIR, "wiretide-ca.key")

    try:
        os.makedirs(CERT_DIR, exist_ok=True)
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", key_path,
            "-out", cert_path,
            "-days", "365",
            "-nodes",
            "-subj", "/CN=Wiretide CA"
        ], check=True)
        return RedirectResponse("/settings", status_code=303)
    except subprocess.CalledProcessError as e:
        print("Cert generation failed:", e)
        raise HTTPException(status_code=500, detail="Certificate generation failed.")
