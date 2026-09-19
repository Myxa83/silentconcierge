# -*- coding: utf-8 -*-
"""Спільне сховище актуального гіру користувачів.

MASTER SPEC: /BDOGEAR_MAIN.md

Нова схема: один MongoDB документ = один Discord user.
Старий документ _id="main" читається як legacy fallback, щоб не втратити
наявні дані під час поступової міграції.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from data.mongo_store import get_database


COLLECTION = "members_gear"
LEGACY_DOCUMENT_ID = "main"


def _users_from_legacy(document: dict | None) -> dict[str, dict]:
    if not isinstance(document, dict):
        return {}

    users = document.get("users")
    if isinstance(users, dict):
        return {
            str(user_id): value
            for user_id, value in users.items()
            if isinstance(value, dict)
        }

    migrated: dict[str, dict] = {}
    for value in document.values():
        if not isinstance(value, dict):
            continue

        user_id = value.get("user_id")
        if user_id is not None:
            migrated[str(user_id)] = value

    return migrated


def _public_entry(document: dict | None) -> dict | None:
    if not isinstance(document, dict):
        return None

    entry = {
        key: value
        for key, value in document.items()
        if key not in {"_id", "schema_version"}
    }
    return entry if entry.get("user_id") is not None else None


def load_gear() -> dict[str, dict]:
    """Повертає весь гір у старому сумісному форматі {user_id: entry}."""
    try:
        collection = get_database()[COLLECTION]

        legacy_document = collection.find_one(
            {"_id": LEGACY_DOCUMENT_ID}
        )
        users = _users_from_legacy(legacy_document)

        for document in collection.find({
            "_id": {"$ne": LEGACY_DOCUMENT_ID},
            "user_id": {"$exists": True},
        }):
            entry = _public_entry(document)
            if not entry:
                continue
            users[str(entry["user_id"])] = entry

        return users
    except Exception as error:
        print(
            f"[GEAR][ERROR] load: {type(error).__name__}: {error}"
        )
        return {}


def upsert_member_gear(
    user_id: int,
    entry: dict[str, Any],
) -> bool:
    """Атомарно зберігає гір одного Discord-користувача."""
    try:
        payload = dict(entry)
        payload["user_id"] = int(user_id)
        payload["updated_at"] = payload.get(
            "updated_at",
            datetime.now(timezone.utc),
        )
        payload["schema_version"] = 2

        get_database()[COLLECTION].update_one(
            {"_id": str(user_id)},
            {"$set": payload},
            upsert=True,
        )
        print(
            f"[GEAR] Збережено user={user_id} "
            f"AP={payload.get('ap')} GS={payload.get('gs')}"
        )
        return True
    except Exception as error:
        print(
            f"[GEAR][ERROR] upsert user={user_id}: "
            f"{type(error).__name__}: {error}"
        )
        return False


def save_gear(users: dict) -> bool:
    """Legacy-compatible bulk save без заміни всього Mongo-документа."""
    ok = True
    for user_id, entry in users.items():
        if not isinstance(entry, dict):
            continue
        try:
            parsed_user_id = int(
                entry.get("user_id", user_id)
            )
        except (TypeError, ValueError):
            print(
                f"[GEAR][ERROR] invalid user id during bulk save: "
                f"{user_id!r}"
            )
            ok = False
            continue

        if not upsert_member_gear(parsed_user_id, entry):
            ok = False

    return ok


def get_member_gear(user_id: int) -> dict | None:
    """Повертає останній гір конкретного Discord-користувача."""
    try:
        collection = get_database()[COLLECTION]

        document = collection.find_one({"_id": str(user_id)})
        entry = _public_entry(document)
        if entry:
            return entry

        legacy = collection.find_one(
            {"_id": LEGACY_DOCUMENT_ID}
        )
        gear = _users_from_legacy(legacy).get(str(user_id))
        return gear if isinstance(gear, dict) else None
    except Exception as error:
        print(
            f"[GEAR][ERROR] get user={user_id}: "
            f"{type(error).__name__}: {error}"
        )
        return None


def count_members() -> int:
    """Кількість унікальних користувачів з гіром."""
    return len(load_gear())
