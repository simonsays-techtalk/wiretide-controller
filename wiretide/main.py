from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Initialize logging
import wiretide.logging  # Sets up /var/log/wiretide.log

# Mount static files FIRST so they're not overridden
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
print(f"Mounting static files from: {STATIC_DIR}")

# Load environment variables
load_dotenv()

# Middleware
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

# Routers (after static mount)
from wiretide.api import devices, auth, system, backup, logs, settings, clients, ui
app.include_router(auth.router)
app.include_router(ui.router)
app.include_router(devices.router)
app.include_router(settings.router)
app.include_router(system.router)
app.include_router(backup.router)
app.include_router(logs.router)
app.include_router(clients.router)

# Optional: Mount agent files LAST so it doesn't override static
app.mount("/", StaticFiles(directory="/var/www/html", html=True), name="agent_files")

# Debug route (for testing)
@app.get("/debug/files")
async def debug_files():
    import os
    return {"dir": STATIC_DIR, "files": os.listdir(STATIC_DIR)}

