"""Interactive Terminal Search Client for Neutron.

Allows running test queries, inspecting BM25 relevance scores, measuring latency,
and testing the JIT live crawler cascade directly from your command line.
"""

import sys
import time
import httpx

GATEWAY_URL = "http://localhost:7860"


def print_banner() -> None:
    print("=" * 70)
    print("   NEUTRON REAL-TIME SEARCH ENGINE (CLI CLIENT)")
    print(f"   Connected Gateway: {GATEWAY_URL}")
    print("=" * 70)


def execute_search(query: str) -> None:
    if not query.strip():
        return

    print(f"\n[Searching]: \"{query}\" ...")
    t0 = time.perf_counter()

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{GATEWAY_URL}/search", params={"q": query, "limit": 10})

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        if resp.status_code != 200:
            print(f"Error ({resp.status_code}): {resp.text}")
            return

        data = resp.json()
        results = data.get("results", [])
        source = data.get("source", "unknown")

        print(f"[Results]: Found {len(results)} matches in {elapsed_ms}ms (Source: {source.upper()})\n")
        print("-" * 70)

        for i, item in enumerate(results, 1):
            title = item.get("title") or "No title"
            url = item.get("url") or ""
            snippet = item.get("snippet") or ""
            score = item.get("score", 0.0)

            print(f"{i}. {title}")
            print(f"   URL:   {url}")
            print(f"   Score: {score} | Hash: {item.get('url_hash')}")
            if snippet:
                print(f"   {snippet[:160]}...")
            print("-" * 70)

    except httpx.ConnectError:
        print(f"\n[Connection Error]: Could not reach Gateway at {GATEWAY_URL}.")
        print("Make sure `docker compose up` or the gateway service is running.")
    except Exception as exc:
        print(f"\n[Unexpected Error]: {exc}")


def main() -> None:
    print_banner()
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        execute_search(query)
        return

    print("Type your search query and press Enter. Type 'exit' or 'quit' to quit.\n")
    while True:
        try:
            query = input("neutron> ").strip()
            if query.lower() in ("exit", "quit"):
                break
            if query:
                execute_search(query)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break


if __name__ == "__main__":
    main()

