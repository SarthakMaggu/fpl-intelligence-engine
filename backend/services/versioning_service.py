from __future__ import annotations

from datetime import datetime
from typing import Optional

import orjson
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db.versioning import DataSnapshot, FeatureVersion, ModelVersion


async def get_or_create_feature_version(
    db: AsyncSession,
    version: str = "feature_store_v2",
    description: str = "Canonical production feature pipeline",
    training_distribution: Optional[dict] = None,
) -> FeatureVersion:
    result = await db.execute(select(FeatureVersion).where(FeatureVersion.version == version))
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    record = FeatureVersion(
        version=version,
        description=description,
        training_distribution_json=orjson.dumps(training_distribution or {}).decode(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def create_data_snapshot(
    db: AsyncSession,
    source: str = "pipeline",
    notes: str | None = None,
) -> DataSnapshot:
    record = DataSnapshot(
        snapshot_key=datetime.utcnow().strftime("%Y%m%d%H%M%S"),
        source=source,
        notes=notes,
        status="active",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def get_or_create_model_version(
    db: AsyncSession,
    *,
    model_name: str,
    version: str,
    artifact_path: str | None = None,
    metrics: Optional[dict] = None,
) -> ModelVersion:
    result = await db.execute(select(ModelVersion).where(ModelVersion.version == version))
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    record = ModelVersion(
        model_name=model_name,
        version=version,
        artifact_path=artifact_path,
        metrics_json=orjson.dumps(metrics or {}).decode(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record
