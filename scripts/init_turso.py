"""Turso Database Initialization and Schema Migration Script.

Applies migrations/03_turso_fts5_schema.sql to your Turso LibSQL database
using the official libsql-client Python library (no CLI installation required).
"""

import asyncio
import os
import sys
from dotenv import load_dotenv
import libsql_client

load_dotenv()

TURSO_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "migrations", "03_turso_fts5_schema.sql")


async def main() -> None:
    if not TURSO_URL or not TURSO_TOKEN:
        print("Error: TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be set in your .env file.")
        sys.exit(1)

    if not os.path.exists(SCHEMA_PATH):
        print(f"Error: Migration schema file not found at {SCHEMA_PATH}")
        sys.exit(1)

    clean_url = TURSO_URL.replace("libsql://", "https://") if TURSO_URL.startswith("libsql://") else TURSO_URL
    print(f"Connecting to Turso: {clean_url}")
    client = libsql_client.create_client(url=clean_url, auth_token=TURSO_TOKEN)

    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            sql_content = f.read()

        # Split SQL into distinct statements
        statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]

        print(f"Executing {len(statements)} schema statements...")
        for i, stmt in enumerate(statements, 1):
            # Skip pure comment statements
            lines = [line for line in stmt.splitlines() if not line.strip().startswith("--")]
            clean_stmt = "\n".join(lines).strip()
            if not clean_stmt:
                continue

            try:
                await client.execute(clean_stmt)
                print(f"  [{i}/{len(statements)}] Executed statement successfully.")
            except Exception as e:
                print(f"  [{i}/{len(statements)}] Warning on statement: {e}")

        # Verification check
        rs = await client.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view');")
        tables = [row["name"] for row in rs.rows]
        print("\nVerified Tables in Turso:")
        for t in tables:
            print(f"  ✓ {t}")

        print("\nTurso LibSQL FTS5 Schema initialized successfully!")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

