# wiretide/main.py
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os

# Initialize logging (rotating file handler)
import wiretide.logging  # Sets up /var/log/wiretide.log

# Import all routers
from wiretide.api import (
    devices,
    auth,
    system,
    backup,
    logs,
    settings,
    clients,
    ui
)

# Middleware to redirect unauthorized users to /login
class RedirectUnauthorizedMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if response.status_code == 401 and request.url.path != "/login":
            from starlette.responses import RedirectResponse
            return RedirectResponse(url="/login")
        return response

# Load environment variables
load_dotenv()

# Create FastAPI app
app = FastAPI()

# Add middleware
app.add_middleware(RedirectUnauthorizedMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("WIRETIDE_SESSION_SECRET", "insecure-default"),
    max_age=3600,
    session_cookie="wiretide_session",
    same_site="lax",
    https_only=True
)

# Register routers
app.include_router(auth.router)
app.include_router(ui.router)
app.include_router(devices.router)
app.include_router(settings.router)
app.include_router(system.router)
app.include_router(backup.router)
app.include_router(logs.router)
app.include_router(clients.router)

# Static file serving
app.mount("/static", StaticFiles(directory="wiretide/static"), name="static")
app.mount("/", StaticFiles(directory="/var/www/html", html=True), name="agent_files")
