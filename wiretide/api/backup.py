# wiretide/api/backup.py
from fastapi import APIRouter, UploadFile, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
import os, tarfile, tempfile, subprocess

from wiretide.api.auth import rbac_required
from wiretide.db import DB_PATH
from wiretide.tokens import ensure_valid_shared_token

CERTS_DIR = "wiretide/certs"

router = APIRouter()

@router.get("/api/backup/download", dependencies=[rbac_required("backup:download")])
async def download_backup():
    """Create a tar.gz backup containing the DB and certs, return as download."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
            with tarfile.open(tmp.name, "w:gz") as tar:
                tar.add(DB_PATH, arcname="wiretide.db")
                if os.path.isdir(CERTS_DIR):
                    tar.add(CERTS_DIR, arcname="certs")
            tmp_path = tmp.name
        return FileResponse(tmp_path, filename="wiretide-backup.tar.gz")
    except Exception as e:
        print("Backup creation failed:", e)
        raise HTTPException(status_code=500, detail="Failed to create backup")


@router.post("/api/backup/restore", dependencies=[rbac_required("backup:restore")])
async def restore_backup(file: UploadFile):
    """Restore the DB and certs from a provided tar.gz backup."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
            contents = await file.read()
            tmp.write(contents)
            tmp_path = tmp.name

        with tarfile.open(tmp_path, "r:gz") as tar:
            for m in tar.getmembers():
                # Only allow DB and certs
                if m.name not in ["wiretide.db"] and not m.name.startswith("certs"):
                    continue
                target_dir = os.path.dirname(DB_PATH) if m.name.endswith(".db") else "wiretide"
                tar.extract(m, path=target_dir)
        return RedirectResponse("/settings", status_code=303)
    except Exception as e:
        print("Backup restore failed:", e)
        raise HTTPException(status_code=500, detail="Failed to restore backup")


@router.post("/api/backup/reset", dependencies=[rbac_required("system:reset")])
async def factory_reset():
    """Perform a factory reset by wiping the DB and regenerating token and certs."""
    try:
        # Remove DB
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

        # Generate a new token (and expiry)
        await ensure_valid_shared_token()

        # Regenerate certs
        os.makedirs(CERTS_DIR, exist_ok=True)
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", f"{CERTS_DIR}/wiretide-ca.key",
            "-out", f"{CERTS_DIR}/wiretide-ca.crt",
            "-days", "365", "-nodes",
            "-subj", "/CN=Wiretide CA"
        ], check=True)

        return RedirectResponse("/settings", status_code=303)
    except Exception as e:
        print("Factory reset failed:", e)
        raise HTTPException(status_code=500, detail="Failed to reset Wiretide")

