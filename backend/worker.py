import asyncio

from services.job_queue import run_worker_loop


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
