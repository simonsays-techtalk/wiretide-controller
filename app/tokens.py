# wiretide/tokens.py
import secrets
from datetime import datetime, timedelta
from wiretide.db import DB_PATH
import aiosqlite

async def get_shared_token() -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM config WHERE key = 'shared_token'")
        row = await cursor.fetchone()
        return row[0] if row else None

async def ensure_valid_shared_token(ttl_minutes: int = 60) -> str:
    now = datetime.utcnow()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM config WHERE key = 'shared_token'")
        token_row = await cursor.fetchone()
        cursor = await db.execute("SELECT value FROM config WHERE key = 'shared_token_expiry'")
        expiry_row = await cursor.fetchone()

        if token_row and expiry_row:
            expiry = datetime.fromisoformat(expiry_row[0])
            if now < expiry:
                return token_row[0]

        # Generate a new token if expired or missing
        new_token = secrets.token_urlsafe(32)
        expiry = now + timedelta(minutes=ttl_minutes)
        await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", ("shared_token", new_token))
        await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", ("shared_token_expiry", expiry.isoformat()))
        await db.commit()
        return new_token

async def update_token(expiry_delta: timedelta) -> str:
    """Force a new token with a specific lifetime."""
    new_token = secrets.token_urlsafe(32)
    new_expiry = datetime.utcnow() + expiry_delta
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", ("shared_token", new_token))
        await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", ("shared_token_expiry", new_expiry.isoformat()))
        await db.commit()
    return new_token
