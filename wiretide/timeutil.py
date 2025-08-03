# wiretide/timeutil.py
from datetime import datetime, timezone

def now() -> datetime:
    """Retourneer huidige hosttijd met tijdzone (als beschikbaar)."""
    return datetime.now().astimezone()



def format_local(dt: datetime | str | None) -> str:
    """Formateer als 'YYYY-MM-DD HH:MM:SS' in lokale tijd.

    Interpreteer naïeve tijden als UTC.
    """
    if not dt:
        return ""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # veilig: timestamps komen van server zelf
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")

