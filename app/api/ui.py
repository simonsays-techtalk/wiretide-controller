# wiretide/api/ui.py
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from wiretide.api.auth import require_login

templates = Jinja2Templates(directory="wiretide/templates")
router = APIRouter()

@router.get("/", include_in_schema=False)
async def root_redirect():
    """Redirect the root URL to the dashboard."""
    return RedirectResponse(url="/index.html")

@router.get("/index.html", response_class=HTMLResponse)
async def serve_index(request: Request, _: str = Depends(require_login)):
    """Main dashboard page."""
    return templates.TemplateResponse("index.html", {"request": request})

@router.get("/clients", response_class=HTMLResponse)
async def serve_clients(request: Request, _: str = Depends(require_login)):
    """Global Clients page (HTML)."""
    # We'll fetch the clients list via the API function (see next section)
    from wiretide.api.clients import get_clients_list  # import helper
    clients = await get_clients_list()
    return templates.TemplateResponse("clients.html", {"request": request, "clients": clients})
