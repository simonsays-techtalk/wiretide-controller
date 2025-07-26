import aiosqlite
import os

# Single source of truth for DB location
DB_PATH = os.getenv("WIRETIDE_DB_PATH", "wiretide/db/wiretide.db")

async def get_db():
    """Return an aiosqlite connection (use with 'async with')."""
    return await aiosqlite.connect(DB_PATH)
