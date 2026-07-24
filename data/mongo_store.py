# -*- coding: utf-8 -*-
"""Спільне сховище робочих даних бота в MongoDB."""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient


_mongo_client: MongoClient | None = None
_mongo_db = None


def get_database():
    """Повертає спільне підключення до бази бота."""
    global _mongo_client, _mongo_db

    if _mongo_db is None:
        mongo_url = os.getenv("MONGODB_URL", "").strip()
        if not mongo_url:
            raise RuntimeError("MONGODB_URL не задано")

        _mongo_client = MongoClient(
            mongo_url,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=10000,
        )
        database_name = os.getenv(
            "MONGODB_DATABASE",
            "silentconcierge",
        ).strip() or "silentconcierge"
        _mongo_db = _mongo_client[database_name]

    return _mongo_db


def load_state(
    collection: str,
    default: Any,
    *,
    document_id: str = "main",
    legacy_path: str | Path | None = None,
) -> Any:
    """Завантажує поле data з одного документа стану."""
    try:
        document = get_database()[collection].find_one(
            {"_id": document_id}
        )
        if isinstance(document, dict) and "data" in document:
            return document["data"]
    except Exception as error:
        print(
            f"[MONGO_STORE][ERROR] load {collection}/{document_id}: "
            f"{type(error).__name__}: {error}"
        )
        return copy.deepcopy(default)

    if legacy_path is not None:
        path = Path(legacy_path)
        if path.exists():
            try:
                raw_text = path.read_text(encoding="utf-8").strip()
                legacy_data = (
                    json.loads(raw_text)
                    if raw_text
                    else copy.deepcopy(default)
                )
                if save_state(
                    collection,
                    legacy_data,
                    document_id=document_id,
                ):
                    print(
                        f"[MONGO_STORE] migrated {path} "
                        f"to {collection}/{document_id}"
                    )
                return legacy_data
            except Exception as error:
                print(
                    f"[MONGO_STORE][ERROR] migrate {path}: "
                    f"{type(error).__name__}: {error}"
                )

    return copy.deepcopy(default)


def save_state(
    collection: str,
    data: Any,
    *,
    document_id: str = "main",
) -> bool:
    """Атомарно замінює один документ стану."""
    try:
        get_database()[collection].replace_one(
            {"_id": document_id},
            {
                "_id": document_id,
                "data": data,
                "updated_at": datetime.now(timezone.utc),
            },
            upsert=True,
        )
        return True
    except Exception as error:
        print(
            f"[MONGO_STORE][ERROR] save {collection}/{document_id}: "
            f"{type(error).__name__}: {error}"
        )
        return False


def append_event(collection: str, event: dict[str, Any]) -> bool:
    """Додає окремий запис журналу без переписування старих записів."""
    try:
        payload = copy.deepcopy(event)
        payload.setdefault(
            "created_at",
            datetime.now(timezone.utc),
        )
        get_database()[collection].insert_one(payload)
        return True
    except Exception as error:
        print(
            f"[MONGO_STORE][ERROR] append {collection}: "
            f"{type(error).__name__}: {error}"
        )
        return False


def migrate_event_file(
    collection: str,
    legacy_path: str | Path,
) -> bool:
    """Одноразово переносить старий JSON-журнал у MongoDB."""
    path = Path(legacy_path)
    if not path.exists():
        return False

    migration_id = f"{collection}:{path.as_posix()}"

    try:
        db = get_database()
        migrations = db["_legacy_json_migrations"]

        if migrations.find_one({"_id": migration_id}):
            return False

        raw_text = path.read_text(encoding="utf-8").strip()
        raw_data = json.loads(raw_text) if raw_text else []
        if isinstance(raw_data, list):
            entries = raw_data
        elif isinstance(raw_data, dict):
            entries = [raw_data]
        else:
            entries = []

        payloads = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            payload = copy.deepcopy(entry)
            payload.setdefault("legacy_source", path.as_posix())
            payload.setdefault(
                "created_at",
                datetime.now(timezone.utc),
            )
            payloads.append(payload)

        if payloads:
            db[collection].insert_many(payloads, ordered=False)

        migrations.insert_one({
            "_id": migration_id,
            "collection": collection,
            "legacy_path": path.as_posix(),
            "records": len(payloads),
            "migrated_at": datetime.now(timezone.utc),
        })
        print(
            f"[MONGO_STORE] migrated {len(payloads)} events "
            f"from {path} to {collection}"
        )
        return True
    except Exception as error:
        print(
            f"[MONGO_STORE][ERROR] migrate events {path}: "
            f"{type(error).__name__}: {error}"
        )
        return False


def migrate_legacy_event_logs() -> None:
    """Переносить відомі журнали та не дублює їх при рестартах."""
    logs_dir = Path("logs")
    if not logs_dir.exists():
        return

    known_logs = {
        "runtime_logs.json": "runtime_logs",
        "post_logs.json": "post_logs",
        "post_tracebacks.json": "post_tracebacks",
    }

    for filename, collection in known_logs.items():
        migrate_event_file(collection, logs_dir / filename)

    for path in logs_dir.glob("banner_changes_*.json"):
        migrate_event_file("server_banner_logs", path)

    for path in logs_dir.glob("????-??-??.json"):
        migrate_event_file("announce_dm_logs", path)


def find_one(
    collection: str,
    query: dict[str, Any],
    projection: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Безпечно читає один документ з довільної колекції."""
    try:
        return get_database()[collection].find_one(query, projection)
    except Exception as error:
        print(
            f"[MONGO_STORE][ERROR] find_one {collection}: "
            f"{type(error).__name__}: {error}"
        )
        return None
