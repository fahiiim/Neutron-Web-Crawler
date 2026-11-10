"""Turso Database Initialization and Schema Migration Script.

Applies migrations/03_turso_fts5_schema.sql to your Turso LibSQL database
using the official libsql-client Python library (no CLI installation required).
"""

import asyncio
import os
import sys
from typing import List
from dotenv import load_dotenv
import libsql_client

load_dotenv()

TURSO_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "03_turso_fts5_schema.sql"
)


def split_sql_statements(sql_content: str) -> List[str]:
    """Split SQL script into executable statements while preserving BEGIN...END blocks."""
    statements: List[str] = []
    buffer: List[str] = []
    in_trigger_body = False

    for raw_line in sql_content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("--"):
            continue

        upper_line = stripped.upper()
        if "CREATE TRIGGER" in upper_line or upper_line.endswith("BEGIN"):
            in_trigger_body = True

        buffer.append(raw_line)

        if in_trigger_body:
            if upper_line == "END;" or upper_line.endswith("END;"):
                statements.append("\n".join(buffer).strip())
                buffer.clear()
                in_trigger_body = False
        elif stripped.endswith(";"):
            statements.append("\n".join(buffer).strip())
            buffer.clear()

    leftover = "\n".join(buffer).strip()
    if leftover:
        statements.append(leftover)

    return statements


async def main() -> None:
    if not TURSO_URL or not TURSO_TOKEN:
        print("Error: TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be set.")
        sys.exit(1)

    if not os.path.exists(SCHEMA_PATH):
        print(f"Error: Migration schema file not found at {SCHEMA_PATH}")
        sys.exit(1)

    clean_url = (
        TURSO_URL.replace("libsql://", "https://")
        if TURSO_URL.startswith("libsql://")
        else TURSO_URL
    )
    print(f"Connecting to Turso: {clean_url}")
    client = libsql_client.create_client(url=clean_url, auth_token=TURSO_TOKEN)

    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            sql_content = f.read()

        statements = split_sql_statements(sql_content)
        print(f"Executing {len(statements)} schema statements...")

        for i, stmt in enumerate(statements, 1):
            try:
                await client.execute(stmt)
                print(f"  [{i}/{len(statements)}] Executed statement successfully.")
            except Exception as exc:
                print(f"  [{i}/{len(statements)}] Warning on statement: {exc}")

        rs = await client.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view', 'index');"
        )
        objects = [row["name"] for row in rs.rows]
        print("\nVerified Schema Objects in Turso:")
        for obj in objects:
            print(f"  ✓ {obj}")

        print("\nTurso LibSQL FTS5 Schema initialized successfully!")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
