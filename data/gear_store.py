# -*- coding: utf-8 -*-
"""Спільне сховище актуального гіру користувачів."""

from __future__ import annotations

from datetime import datetime, timezone

from data.mongo_store import get_database


COLLECTION = "members_gear"
DOCUMENT_ID = "main"


def _users_from_document(document: dict | None) -> tuple[dict, bool]:
    if not isinstance(document, dict):
        return {}, False

    users = document.get("users")
    if isinstance(users, dict):
        return users, False

    migrated = {}
    for value in document.values():
        if not isinstance(value, dict):
            continue

        user_id = value.get("user_id")
        if user_id is not None:
            migrated[str(user_id)] = value

    return migrated, bool(migrated)


def load_gear() -> dict:
    """Повертає гір за Discord ID та мігрує стару схему."""
    try:
        document = get_database()[COLLECTION].find_one(
            {"_id": DOCUMENT_ID}
        )
        users, needs_migration = _users_from_document(document)
        if needs_migration:
            save_gear(users)
        return users
    except Exception as error:
        print(
            f"[GEAR][ERROR] load: {type(error).__name__}: {error}"
        )
        return {}


def save_gear(users: dict) -> bool:
    """Зберігає гір усіх користувачів в одному документі."""
    try:
        get_database()[COLLECTION].replace_one(
            {"_id": DOCUMENT_ID},
            {
                "_id": DOCUMENT_ID,
                "users": users,
                "updated_at": datetime.now(timezone.utc),
            },
            upsert=True,
        )
        print(f"[GEAR] Збережено гравців: {len(users)}")
        return True
    except Exception as error:
        print(
            f"[GEAR][ERROR] save: {type(error).__name__}: {error}"
        )
        return False


def get_member_gear(user_id: int) -> dict | None:
    """Повертає останній гір конкретного Discord-користувача."""
    gear = load_gear().get(str(user_id))
    return gear if isinstance(gear, dict) else None
