import asyncio
import os
from dotenv import load_dotenv
import libsql_client

load_dotenv()

async def inspect():
    db_url = os.environ.get("TURSO_DATABASE_URL", "").replace("libsql://", "https://")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    client = libsql_client.create_client(url=db_url, auth_token=token)

    r1 = await client.execute("SELECT COUNT(*) as cnt FROM search_index;")
    r2 = await client.execute("SELECT COUNT(*) as cnt FROM page_payloads;")
    r3 = await client.execute("SELECT COUNT(*) as cnt FROM frontier_queue;")
    r4 = await client.execute("SELECT term, frequency FROM hot_topics ORDER BY frequency DESC LIMIT 5;")

    print("=== Turso LibSQL Database Metrics ===")
    print("Indexed Search Documents:", r1.rows[0]["cnt"])
    print("Compressed Zstd Payloads:", r2.rows[0]["cnt"])
    print("Frontier Queue URLs:", r3.rows[0]["cnt"])
    print("Top Searched Topics:")
    for row in r4.rows:
        print(f"  - '{row['term']}': {row['frequency']} searches")
    await client.close()

if __name__ == "__main__":
    asyncio.run(inspect())
