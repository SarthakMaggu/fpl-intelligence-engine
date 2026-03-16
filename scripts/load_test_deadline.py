#!/usr/bin/env python3
"""
Lightweight deadline-window load test.

Usage:
  API_URL=http://localhost:8000 python3 scripts/load_test_deadline.py
"""

import asyncio
import os
import random
import time

import httpx


API_URL = os.getenv("API_URL", "http://localhost:8000")
TEAM_IDS = [8433551 + i for i in range(500)]


async def hit_endpoint(client: httpx.AsyncClient, path: str, team_id: int) -> float:
    start = time.perf_counter()
    response = await client.get(f"{API_URL}{path}", params={"team_id": team_id})
    response.raise_for_status()
    return time.perf_counter() - start


async def run_user_flow(client: httpx.AsyncClient, team_id: int) -> list[float]:
    durations = []
    for path in ["/api/squad/", "/api/intel/gw", "/api/optimization/captain", "/api/review/season"]:
        try:
            durations.append(await hit_endpoint(client, path, team_id))
        except Exception:
            durations.append(-1.0)
    return durations


async def main() -> None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        tasks = [run_user_flow(client, team_id) for team_id in TEAM_IDS]
        results = await asyncio.gather(*tasks)
    flat = [value for row in results for value in row if value >= 0]
    failures = sum(1 for row in results for value in row if value < 0)
    if flat:
        print(f"requests={len(flat)} failures={failures} avg_ms={sum(flat)/len(flat)*1000:.1f} p95_ms={sorted(flat)[int(len(flat)*0.95)-1]*1000:.1f}")
    else:
        print(f"requests=0 failures={failures}")


if __name__ == "__main__":
    asyncio.run(main())
