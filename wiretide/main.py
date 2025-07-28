from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os
from wiretide.api import roles
from fastapi.responses import FileResponse

app = FastAPI()  # <-- Define app FIRST

# Directories
STATIC_DIR = "/opt/wiretide/wiretide/static"

# Initialize logging (rotating file handler)
import wiretide.logging  # Sets up /var/log/wiretide.log

# Mount static (logo, agent files, CA cert)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
print(f"Mounting static files from: {STATIC_DIR}")

# Load environment variables
load_dotenv()

# Middleware for login redirection
class RedirectUnauthorizedMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if response.status_code == 401 and request.url.path != "/login":
            from starlette.responses import RedirectResponse
            return RedirectResponse(url="/login")
        return response

app.add_middleware(RedirectUnauthorizedMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("WIRETIDE_SESSION_SECRET", "insecure-default"),
    max_age=3600,
    session_cookie="wiretide_session",
    same_site="lax",
    https_only=True
)

# Import routers (after static)
from wiretide.api import devices, auth, system, backup, logs, settings, clients, ui
app.include_router(auth.router)
app.include_router(ui.router)
app.include_router(devices.router)
app.include_router(settings.router)
app.include_router(system.router, prefix="/api")
app.include_router(backup.router)
app.include_router(logs.router)
app.include_router(clients.router)
app.include_router(roles.router)

# Shortcut for CA certificate (agents will wget this directly)
@app.get("/ca.crt")
async def get_ca():
    ca_path = os.path.join(STATIC_DIR, "ca.crt")
    return FileResponse(ca_path)

