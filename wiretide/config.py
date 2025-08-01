# wiretide/config.py
import aiosqlite
from wiretide.db import DB_PATH

async def get_config_value(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else default

