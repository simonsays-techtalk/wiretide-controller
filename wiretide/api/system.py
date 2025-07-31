# wiretide/api/system.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
import os, re, subprocess, socket, hashlib, threading, time

from wiretide.api.auth import rbac_required

LOG_FILE = "/var/log/wiretide.log"
CERT_DIR = "wiretide/certs"

router = APIRouter()


def get_process_uptime():
    """Bepaal de uptime (in seconden) van het huidige Wiretide-proces via /proc."""
    try:
        with open("/proc/self/stat") as f:
            fields = f.read().split()
            start_ticks = int(fields[21])

        ticks_per_sec = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        process_start_time = start_ticks / ticks_per_sec

        with open("/proc/uptime") as f:
            system_uptime = float(f.readline().split()[0])

        uptime_seconds = system_uptime - process_start_time
        if uptime_seconds < 0:
            uptime_seconds = 0
        return int(uptime_seconds)
    except Exception:
        return None


@router.get("/api/logs", dependencies=[rbac_required("logs:view")])
async def get_logs(level: str = "ALL"):
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
        regex = re.compile(rf"\b{re.escape(level)}\b")
        lines = [line for line in lines if regex.search(line)]
    return {"lines": lines}


@router.get("/api/logs/download", dependencies=[rbac_required("logs:download")])
async def download_logs():
    """Download the raw log file."""
    try:
        return FileResponse(LOG_FILE, filename="wiretide.log")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Log file not found")


@router.get("/api/system-info", dependencies=[rbac_required("system:view")])
async def system_info():
    """Return controller diagnostics: hostname, IP, controller uptime, version, certs, agent info."""
    hostname = socket.gethostname()

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "unknown"

    uptime_seconds = get_process_uptime()
    if uptime_seconds is not None:
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        if days > 0:
            uptime = f"{days}d {hours}h {minutes}m"
        else:
            uptime = f"{hours}h {minutes}m"
    else:
        uptime = "unknown"

    version = "V0.5.5 Alpha"

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

    agent_zip = "wiretide/static/agent/wiretide-agent.zip"
    if os.path.exists(agent_zip):
        with open(agent_zip, "rb") as f:
            checksum = hashlib.sha256(f.read()).hexdigest()
        agent_url = "/static/agent/wiretide-agent.zip"
    else:
        checksum = "not found"
        agent_url = None

    return JSONResponse({
        "hostname": hostname,
        "ip": ip,
        "uptime": uptime,
        "version": version,
        "cert_type": cert_type,
        "cert_expiry": expiry,
        "agent_version": "0.5.5 Alpha",
        "agent_checksum": checksum,
        "agent_url": agent_url
    })


@router.post("/api/restart", dependencies=[rbac_required("system:restart")])
async def restart_controller():
    """Restart the Wiretide systemd service using sudo so NOPASSWD sudoers works."""
    try:
        subprocess.Popen(["sudo", "systemctl", "restart", "wiretide.service"])
    except Exception as e:
        print("Restart failed:", e)
        raise HTTPException(status_code=500, detail=f"Failed to restart Wiretide: {e}")
    return RedirectResponse("/settings", status_code=303)


@router.post("/api/cert/regenerate", dependencies=[rbac_required("cert:regenerate")])
async def regenerate_cert():
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


def delayed_restart():
    time.sleep(1)
    subprocess.run(["sudo", "systemctl", "restart", "wiretide.service"], check=False)


@router.post("/restart", dependencies=[rbac_required("system:restart")])
def restart_service():
    """Trigger a delayed service restart (non-API endpoint)."""
    threading.Thread(target=delayed_restart, daemon=True).start()
    return {"status": "restarting"}

