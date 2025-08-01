import os
import tarfile
import tempfile
import subprocess
import shutil

from fastapi import APIRouter, UploadFile, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from wiretide.api.auth import rbac_required
from wiretide.db import DB_PATH
from wiretide.tokens import ensure_valid_shared_token


CERTS_DIR = "/opt/wiretide/certs"
DB_FILE = DB_PATH  
WIRETIDE_DIR = os.path.dirname(DB_FILE)
SERVICE_USER = "wiretide"
SERVICE_GROUP = "wiretide"

router = APIRouter()

def fix_permissions():
    """Herstel standaard permissies voor DB, directories en certs."""
    try:
        # Data-directory correct zetten
        os.chmod(WIRETIDE_DIR, 0o770)
        shutil.chown(WIRETIDE_DIR, user=SERVICE_USER, group=SERVICE_GROUP)

        # Database eigendom en rechten
        if os.path.exists(DB_FILE):
            shutil.chown(DB_FILE, user=SERVICE_USER, group=SERVICE_GROUP)
            os.chmod(DB_FILE, 0o660)

        # Oude SQLite-journalbestanden verwijderen
        for f in os.listdir(WIRETIDE_DIR):
            if f.startswith("wiretide.db-"):
                os.remove(os.path.join(WIRETIDE_DIR, f))

        # Cert-directory rechten herstellen
        if os.path.isdir(CERTS_DIR):
            os.chmod(CERTS_DIR, 0o750)
            shutil.chown(CERTS_DIR, user="root", group=SERVICE_GROUP)
            for root, dirs, files in os.walk(CERTS_DIR):
                for d in dirs:
                    shutil.chown(os.path.join(root, d), user="root", group=SERVICE_GROUP)
                    os.chmod(os.path.join(root, d), 0o750)
                for f in files:
                    path = os.path.join(root, f)
                    if f.endswith(".key"):
                        os.chmod(path, 0o640)
                        shutil.chown(path, user="root", group=SERVICE_GROUP)
                    else:
                        os.chmod(path, 0o644)
                        shutil.chown(path, user="root", group=SERVICE_GROUP)
    except Exception as e:
        print(f"Permission fix failed: {e}")

def restart_service():
    """Herstart de Wiretide-service zodat nieuwe DB en certs actief zijn."""
    try:
        subprocess.run(["systemctl", "restart", "wiretide"], check=True)
    except Exception as e:
        print(f"Failed to restart Wiretide service: {e}")

@router.get("/api/backup/download", dependencies=[rbac_required("backup:download")])
async def download_backup():
    """Maak een tar.gz backup met DB en certificaten."""
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

def is_within_directory(directory, target):
    abs_directory = os.path.abspath(directory)
    abs_target = os.path.abspath(target)
    return os.path.commonpath([abs_directory]) == os.path.commonpath([abs_directory, abs_target])

def safe_extract(tar: tarfile.TarFile, path: str = "."):
    for member in tar.getmembers():
        member_path = os.path.join(path, member.name)
        if not is_within_directory(path, member_path):
            raise Exception(f"Unsafe path detected in archive: {member.name}")
    tar.extractall(path)

@router.post("/api/backup/restore", dependencies=[rbac_required("backup:restore")])
async def restore_backup(file: UploadFile):
    """Herstel database en certificaten uit een tar.gz backup, fix permissies, en restart service."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
            contents = await file.read()
            tmp.write(contents)
            tmp_path = tmp.name

        with tarfile.open(tmp_path, "r:gz") as tar:
            temp_extract = tempfile.mkdtemp()
            safe_extract(tar, temp_extract)

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

        fix_permissions()
        restart_service()

        return RedirectResponse("/settings", status_code=303)
    except Exception as e:
        print("Backup restore failed:", e)
        raise HTTPException(status_code=500, detail="Failed to restore backup")

@router.post("/api/backup/reset", dependencies=[rbac_required("system:reset")])
async def factory_reset():
    """Wist DB en certs, genereert nieuw token, self-signed certs, herstelt permissies en restart service."""
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

        # Rechten herstellen en service opnieuw starten
        fix_permissions()
        restart_service()

        return RedirectResponse("/settings", status_code=303)
    except Exception as e:
        print("Factory reset failed:", e)
        raise HTTPException(status_code=500, detail="Failed to reset Wiretide")

