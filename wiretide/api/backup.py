# wiretide/api/backup.py
from fastapi import APIRouter, UploadFile, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
import os, tarfile, tempfile, subprocess, shutil

from wiretide.api.auth import rbac_required
from wiretide.db import DB_PATH
from wiretide.tokens import ensure_valid_shared_token

# Absolute paden voor de alpha-setup
CERTS_DIR = "/etc/wiretide/certs"
DB_FILE = DB_PATH  # doorgaans /opt/wiretide/wiretide.db

router = APIRouter()

@router.get("/api/backup/download", dependencies=[rbac_required("backup:download")])
async def download_backup():
    """Maak een tar.gz backup met de DB en certificaten."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Kopieer DB
            if os.path.exists(DB_FILE):
                shutil.copy2(DB_FILE, os.path.join(tmpdir, "wiretide.db"))

            # Kopieer certs
            cert_tmp = os.path.join(tmpdir, "certs")
            if os.path.isdir(CERTS_DIR):
                shutil.copytree(CERTS_DIR, cert_tmp, dirs_exist_ok=True)

            # Maak tarball
            tmp_tar = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
            with tarfile.open(tmp_tar.name, "w:gz") as tar:
                tar.add(os.path.join(tmpdir, "wiretide.db"), arcname="wiretide.db")
                if os.path.isdir(cert_tmp):
                    tar.add(cert_tmp, arcname="certs")

        return FileResponse(tmp_tar.name, filename="wiretide-backup.tar.gz")
    except Exception as e:
        print("Backup creation failed:", e)
        raise HTTPException(status_code=500, detail="Failed to create backup")


@router.post("/api/backup/restore", dependencies=[rbac_required("backup:restore")])
async def restore_backup(file: UploadFile):
    """Herstel database en certificaten uit een tar.gz backup."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
            contents = await file.read()
            tmp.write(contents)
            tmp_path = tmp.name

        with tarfile.open(tmp_path, "r:gz") as tar:
            temp_extract = tempfile.mkdtemp()
            tar.extractall(temp_extract)

            # Database herstellen
            db_src = os.path.join(temp_extract, "wiretide.db")
            if os.path.exists(db_src):
                shutil.move(db_src, DB_FILE)

            # Certificaten herstellen
            cert_src = os.path.join(temp_extract, "certs")
            if os.path.isdir(cert_src):
                os.makedirs(CERTS_DIR, exist_ok=True)
                for root, dirs, files in os.walk(cert_src):
                    rel = os.path.relpath(root, cert_src)
                    dest_root = os.path.join(CERTS_DIR, rel) if rel != "." else CERTS_DIR
                    os.makedirs(dest_root, exist_ok=True)
                    for f in files:
                        shutil.copy2(os.path.join(root, f), dest_root)

        return RedirectResponse("/settings", status_code=303)
    except Exception as e:
        print("Backup restore failed:", e)
        raise HTTPException(status_code=500, detail="Failed to restore backup")


@router.post("/api/backup/reset", dependencies=[rbac_required("system:reset")])
async def factory_reset():
    """Wist DB en certs, genereert nieuw token en self-signed certs."""
    try:
        # DB verwijderen
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)

        # Nieuwe token genereren
        await ensure_valid_shared_token()

        # Certs opnieuw genereren
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

