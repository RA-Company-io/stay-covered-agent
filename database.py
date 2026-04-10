"""
SQLite database layer - leads + messages
"""

import aiosqlite
import os
from datetime import datetime
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "staycovered.db")

# Cria o diretório se não existir
import pathlib
pathlib.Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_wpp TEXT UNIQUE NOT NULL,
                nome TEXT,
                email TEXT,
                telefone TEXT,
                data_nascimento TEXT,
                driver_license TEXT,
                estado_civil TEXT,
                endereco TEXT,
                vin TEXT,
                imovel_tipo TEXT,
                status TEXT DEFAULT 'Iniciado',
                bot_ativo INTEGER DEFAULT 1,
                follow_up_stage INTEGER DEFAULT 0,
                last_message_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            )
        """)
        await db.commit()


def now() -> str:
    return datetime.utcnow().isoformat()


# ─── LEADS ────────────────────────────────────────────────────────────────────

async def get_or_create_lead(numero_wpp: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM leads WHERE numero_wpp = ?", (numero_wpp,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)

        ts = now()
        await db.execute(
            """INSERT INTO leads (numero_wpp, status, bot_ativo, follow_up_stage,
               last_message_at, created_at, updated_at)
               VALUES (?, 'Iniciado', 1, 0, ?, ?, ?)""",
            (numero_wpp, ts, ts, ts)
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM leads WHERE numero_wpp = ?", (numero_wpp,)
        ) as cursor:
            return dict(await cursor.fetchone())


async def update_lead_fields(lead_id: int, fields: dict):
    if not fields:
        return
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [lead_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE leads SET {cols} WHERE id = ?", vals)
        await db.commit()


async def update_last_message(lead_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        ts = now()
        await db.execute(
            "UPDATE leads SET last_message_at = ?, updated_at = ?, follow_up_stage = 0 WHERE id = ?",
            (ts, ts, lead_id)
        )
        await db.commit()


async def get_all_leads() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM leads ORDER BY updated_at DESC"
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_lead_by_id(lead_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM leads WHERE id = ?", (lead_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_leads_for_followup() -> list[dict]:
    """Returns leads eligible for a follow-up check."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM leads
            WHERE bot_ativo = 1
              AND status NOT IN ('Pronto para cotar', 'Cotado', 'Fechado', 'FUP EXTENDIDO')
              AND follow_up_stage < 4
              AND last_message_at IS NOT NULL
        """) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


# ─── MESSAGES ─────────────────────────────────────────────────────────────────

async def save_message(lead_id: int, role: str, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (lead_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (lead_id, role, content, now())
        )
        await db.commit()


async def get_messages(lead_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE lead_id = ? ORDER BY id ASC",
            (lead_id,)
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_messages_for_agent(lead_id: int) -> list[dict]:
    """Returns messages in Claude API format (role + content only)."""
    msgs = await get_messages(lead_id)
    return [{"role": m["role"], "content": m["content"]} for m in msgs
            if m["role"] in ("user", "assistant")]


async def get_new_messages_since(lead_id: int, since_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE lead_id = ? AND id > ? ORDER BY id ASC",
            (lead_id, since_id)
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]
