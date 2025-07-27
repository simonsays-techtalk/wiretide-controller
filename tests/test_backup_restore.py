import os
import tarfile
import io
from fastapi import FastAPI
from fastapi.testclient import TestClient


def create_test_app():
    """Return FastAPI app with backup router and login override."""
    from wiretide.api import backup
    from wiretide.api.auth import require_login

    app = FastAPI()
    app.include_router(backup.router)
    app.dependency_overrides[require_login] = lambda: None
    return app


def make_backup_tar() -> bytes:
    """Create a tar.gz archive containing a dummy DB file."""
    data = b"dummy"
    f = io.BytesIO()
    with tarfile.open(fileobj=f, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="wiretide.db")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return f.getvalue()


def test_restore_places_db_at_db_path(tmp_path, monkeypatch):
    db_dir = tmp_path / "data"
    db_file = db_dir / "wiretide.db"
    monkeypatch.setenv("WIRETIDE_DB_PATH", str(db_file))

    # Reload modules so DB_PATH picks up env var
    import importlib
    import wiretide.db
    import wiretide.api.backup
    importlib.reload(wiretide.db)
    importlib.reload(wiretide.api.backup)

    app = create_test_app()
    client = TestClient(app)

    archive = make_backup_tar()

    response = client.post(
        "/api/backup/restore",
        files={"file": ("backup.tar.gz", archive, "application/gzip")},
        allow_redirects=False,
    )

    assert response.status_code == 303
    assert db_file.exists()
    assert not os.path.exists(os.path.join("wiretide", "db", "wiretide.db"))
