# wiretide/timeutil.py

from datetime import datetime

def now() -> datetime:
    """Retourneer huidige hosttijd met tijdzone (als beschikbaar)."""
    return datetime.now().astimezone()

def now_iso() -> str:
    """ISO-formaat met tijdzone, zonder microseconden."""
    return now().isoformat(sep=" ", timespec="seconds")

def format_local(dt: datetime | str | None) -> str:
    """Formateer als 'YYYY-MM-DD HH:MM:SS' in lokale tijd."""
    if not dt:
        return ""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.astimezone()  # neem host tijdzone aan
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")

