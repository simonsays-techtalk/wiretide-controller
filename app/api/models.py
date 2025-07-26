from pydantic import BaseModel
from typing import Dict, Any, List, Optional

class DeviceStatus(BaseModel):
    hostname: str
    mac: str
    ssh_fingerprint: Optional[str] = None
    ssh_enabled: bool = True
    settings: Optional[Dict[str, Any]] = {}
    clients: Optional[List[Dict[str, Any]]] = []
