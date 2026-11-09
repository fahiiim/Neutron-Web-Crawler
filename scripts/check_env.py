"""Environment and Cloud Credentials Pre-Flight Verification Script.

Tests connections to Turso LibSQL and Cloudflare R2 before deployment,
ensuring all credentials and endpoints are valid.
"""

import asyncio
import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

TURSO_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
R2_ENDPOINT = os.getenv("R2_ENDPOINT_URL")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET_NAME", "neutron-page-cache")
INTERNAL_KEY = os.getenv("INTERNAL_API_KEY")


async def test_turso() -> bool:
    print("\n[1/3] Testing Turso LibSQL Database...")
    if not TURSO_URL or not TURSO_TOKEN:
        print("  ❌ Missing TURSO_DATABASE_URL or TURSO_AUTH_TOKEN in .env")
        return False

    try:
        import libsql_client
        t0 = time.perf_counter()
        client = libsql_client.create_client_async(url=TURSO_URL, auth_token=TURSO_TOKEN)
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


async def test_r2() -> bool:
    print("\n[2/3] Testing Cloudflare R2 S3 Storage...")
    if not R2_ENDPOINT or not R2_ACCESS_KEY or not R2_SECRET_KEY:
        print("  ⚠️ Cloudflare R2 credentials not fully set in .env (skipping object storage test)")
        print("     (Local disk fallback will be used until R2 credentials are provided)")
        return True

    try:
        import aioboto3
        session = aioboto3.Session()
        test_key = "preflight_test_chunk.bin"
        test_data = b"Neutron Crawler Pre-Flight Verification Payload"

        t0 = time.perf_counter()
        async with session.client(
            "s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            region_name="auto",
        ) as s3:
            # 1. Test Put Object
            await s3.put_object(
                Bucket=R2_BUCKET,
                Key=test_key,
                Body=test_data,
                ContentType="application/octet-stream",
            )

            # 2. Test Byte-Range Get Object
            resp = await s3.get_object(
                Bucket=R2_BUCKET,
                Key=test_key,
                Range="bytes=0-14",
            )
            async with resp["Body"] as stream:
                read_back = await stream.read()

            # 3. Clean up test object
            await s3.delete_object(Bucket=R2_BUCKET, Key=test_key)

        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        if read_back == test_data[:15]:
            print(f"  ✓ Connected to Cloudflare R2! Byte-range read verified. (Roundtrip: {elapsed}ms)")
            return True
        else:
            print("  ❌ R2 verification byte-range mismatch.")
            return False
    except Exception as exc:
        print(f"  ❌ Cloudflare R2 test failed: {exc}")
        return False


def test_internal_key() -> bool:
    print("\n[3/3] Testing Internal Inter-Service Key...")
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
    r2_ok = await test_r2()
    key_ok = test_internal_key()

    print("\n" + "=" * 65)
    if turso_ok and r2_ok and key_ok:
        print("  🎉 ALL CHECKS PASSED! You are ready to deploy to Hugging Face Spaces.")
    else:
        print("  ⚠️ Please update missing credentials in .env before deploying.")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
