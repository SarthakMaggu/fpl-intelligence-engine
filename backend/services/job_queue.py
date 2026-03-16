from __future__ import annotations

import asyncio
import importlib
from datetime import datetime
from typing import Any, Awaitable, Callable
from uuid import uuid4

import orjson
from loguru import logger
from sqlalchemy import select

from core.config import settings
from core.redis_client import redis_client
from core.database import AsyncSessionLocal
from models.db.background_job import BackgroundJob
from services.metrics_service import metrics_registry

JOB_HANDLERS: dict[str, str] = {
    "backtest.run": "services.job_tasks:run_backtest_job",
    "oracle.auto_resolve": "services.job_tasks:run_oracle_auto_resolve_job",
    "pipeline.full": "services.job_tasks:run_full_pipeline_job",
    "monitor.feature_drift": "services.job_tasks:run_feature_drift_job",
}


async def enqueue_job(
    *,
    job_type: str,
    payload: dict[str, Any],
    max_attempts: int = 3,
    priority: int = 5,
) -> dict[str, Any]:
    job_id = str(uuid4())
    now = datetime.utcnow()
    job = BackgroundJob(
        job_id=job_id,
        job_type=job_type,
        status="queued",
        max_attempts=max_attempts,
        priority=priority,
        payload_json=orjson.dumps(payload).decode(),
        created_at=now,
    )
    async with AsyncSessionLocal() as db:
        db.add(job)
        await db.commit()
    await redis_client.rpush(settings.JOB_QUEUE_KEY, job_id)
    await _cache_job_state(job_id)
    metrics_registry.inc("job_enqueued_total", 1)
    return {"job_id": job_id, "status": "queued", "job_type": job_type}


async def get_job(job_id: str) -> BackgroundJob | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(BackgroundJob).where(BackgroundJob.job_id == job_id))
        return result.scalar_one_or_none()


async def get_job_state(job_id: str) -> dict[str, Any] | None:
    raw = await redis_client.get(f"job:{job_id}")
    if raw:
        return orjson.loads(raw)
    job = await get_job(job_id)
    if not job:
        return None
    return await _cache_job_state(job_id, job=job)


async def _cache_job_state(job_id: str, job: BackgroundJob | None = None) -> dict[str, Any]:
    if job is None:
        job = await get_job(job_id)
    if job is None:
        return {}
    payload = {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "status": job.status,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "result": orjson.loads(job.result_json) if job.result_json else None,
        "error": job.error,
    }
    await redis_client.set(f"job:{job_id}", orjson.dumps(payload).decode(), ex=86400)
    return payload


def _load_handler(job_type: str) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    ref = JOB_HANDLERS[job_type]
    module_name, handler_name = ref.split(":")
    module = importlib.import_module(module_name)
    return getattr(module, handler_name)


async def run_worker_loop() -> None:
    logger.info("Starting Redis job worker loop")
    while True:
        try:
            item = await redis_client.blpop(settings.JOB_QUEUE_KEY, timeout=5)
            if not item:
                metrics_registry.set_gauge("job_queue_depth", float(await redis_client.llen(settings.JOB_QUEUE_KEY)))
                continue
            _, job_id = item
            await process_job(job_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Worker loop error: {exc}")
            metrics_registry.inc("worker_failure_total", 1)
            await asyncio.sleep(settings.WORKER_POLL_INTERVAL_MS / 1000)


async def process_job(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(BackgroundJob).where(BackgroundJob.job_id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return
        if job.status == "succeeded":
            return
        job.status = "running"
        job.attempts += 1
        job.started_at = datetime.utcnow()
        await db.commit()
        await _cache_job_state(job_id, job=job)

    try:
        handler = _load_handler(job.job_type)
        payload = orjson.loads(job.payload_json or "{}")
        result_payload = await handler(payload)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(BackgroundJob).where(BackgroundJob.job_id == job_id))
            job = result.scalar_one()
            job.status = "succeeded"
            job.completed_at = datetime.utcnow()
            job.result_json = orjson.dumps(result_payload).decode()
            job.error = None
            await db.commit()
            await _cache_job_state(job_id, job=job)
        metrics_registry.inc("job_succeeded_total", 1)
    except Exception as exc:
        logger.exception(f"Job {job_id} failed: {exc}")
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(BackgroundJob).where(BackgroundJob.job_id == job_id))
            job = result.scalar_one()
            job.error = str(exc)
            if job.attempts < job.max_attempts:
                job.status = "retrying"
                await db.commit()
                await redis_client.rpush(settings.JOB_QUEUE_KEY, job_id)
            else:
                job.status = "failed"
                job.completed_at = datetime.utcnow()
                await db.commit()
            await _cache_job_state(job_id, job=job)
        metrics_registry.inc("job_failed_total", 1)
