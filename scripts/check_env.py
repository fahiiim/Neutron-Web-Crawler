"""Environment and Cloud Credentials Pre-Flight Verification Script.

Tests connection to Turso LibSQL database and internal keys before deployment.
Cloudflare R2 is now optional because Turso stores full-text payloads directly.
"""

import asyncio
import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

TURSO_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
INTERNAL_KEY = os.getenv("INTERNAL_API_KEY")


async def test_turso() -> bool:
    print("\n[1/2] Testing Turso LibSQL Database (100% Free, Zero-Card)...")
    if not TURSO_URL or not TURSO_TOKEN:
        print("  ❌ Missing TURSO_DATABASE_URL or TURSO_AUTH_TOKEN in .env")
        return False

    try:
        import libsql_client
        clean_url = TURSO_URL.replace("libsql://", "https://") if TURSO_URL.startswith("libsql://") else TURSO_URL
        t0 = time.perf_counter()
        client = libsql_client.create_client(url=clean_url, auth_token=TURSO_TOKEN)
        rs = await client.execute("SELECT 1 AS alive;")
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        await client.close()

        if rs.rows and rs.rows[0]["alive"] == 1:
            print(f"  ✓ Connected to Turso successfully! (Roundtrip: {elapsed}ms)")
            return True
        else:
            print("  ❌ Unexpected response from Turso.")
            return False
    except Exception as exc:
        print(f"  ❌ Turso connection failed: {exc}")
        return False


def test_internal_key() -> bool:
    print("\n[2/2] Testing Internal Inter-Service Key...")
    if not INTERNAL_KEY or len(INTERNAL_KEY) < 16 or "change_me" in INTERNAL_KEY:
        print("  ⚠️ INTERNAL_API_KEY is missing or using default placeholder.")
        print("     Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"")
        return False
    print("  ✓ Internal API key is secure and configured.")
    return True


async def main() -> None:
    print("=" * 65)
    print("   NEUTRON SEARCH ENGINE: PRE-FLIGHT CREDENTIAL CHECK")
    print("=" * 65)

    turso_ok = await test_turso()
    key_ok = test_internal_key()

    print("\n" + "=" * 65)
    if turso_ok and key_ok:
        print("  🎉 ALL REQUIRED CHECKS PASSED!")
        print("  No credit card required. Ready to deploy to Hugging Face Spaces.")
    else:
        print("  ⚠️ Please update missing credentials in .env before deploying.")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
