# -*- coding: utf-8 -*-
"""MongoDB storage for Black Shrine daily interest and parties."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pymongo import ReturnDocument

from data.mongo_store import get_database


DAILY_COLLECTION = "shrine_daily"
PARTY_COLLECTION = "shrine_parties"
META_COLLECTION = "shrine_meta"

ACTIVE_STATUSES = ["searching", "closed"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _db():
    return get_database()


def set_today_member(
    day: str,
    user_id: int,
    display_name: str,
    available: bool,
) -> None:
    collection = _db()[DAILY_COLLECTION]
    key = f"{day}:{int(user_id)}"

    if not available:
        collection.delete_one({"_id": key})
        return

    collection.update_one(
        {"_id": key},
        {
            "$set": {
                "date": day,
                "user_id": int(user_id),
                "display_name": display_name,
                "updated_at": _now(),
            },
            "$setOnInsert": {
                "joined_at": _now(),
            },
        },
        upsert=True,
    )


def list_today_members(day: str) -> list[dict]:
    return list(
        _db()[DAILY_COLLECTION]
        .find({"date": day})
        .sort("joined_at", 1)
    )


def is_today_member(day: str, user_id: int) -> bool:
    return (
        _db()[DAILY_COLLECTION].find_one(
            {"_id": f"{day}:{int(user_id)}"},
            {"_id": 1},
        )
        is not None
    )


def save_daily_panel(day: str, channel_id: int, message_id: int) -> None:
    _db()[META_COLLECTION].update_one(
        {"_id": f"panel:{day}"},
        {
            "$set": {
                "date": day,
                "channel_id": int(channel_id),
                "message_id": int(message_id),
                "updated_at": _now(),
            }
        },
        upsert=True,
    )


def get_daily_panel(day: str) -> dict | None:
    return _db()[META_COLLECTION].find_one({"_id": f"panel:{day}"})


def create_party(
    *,
    day: str,
    leader_id: int,
    activity: str,
    time_text: str,
    notes: str,
    requirement_ap: int,
    gear_snapshot: dict,
) -> dict:
    party_id = uuid4().hex[:12]
    uid = str(int(leader_id))

    document = {
        "_id": party_id,
        "date": day,
        "status": "searching",
        "leader_id": int(leader_id),
        "requirement_ap": int(requirement_ap),
        "max_members": 5,
        "activity": activity.strip() or "Black Shrine",
        "time_text": time_text.strip() or "Не вказано",
        "notes": notes.strip(),
        "members": [int(leader_id)],
        "pending": [],
        "declined": [],
        "gear_snapshots": {uid: dict(gear_snapshot or {})},
        "channel_id": None,
        "message_id": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _db()[PARTY_COLLECTION].insert_one(document)
    return document


def set_party_message(party_id: str, channel_id: int, message_id: int) -> dict | None:
    return _db()[PARTY_COLLECTION].find_one_and_update(
        {"_id": party_id},
        {
            "$set": {
                "channel_id": int(channel_id),
                "message_id": int(message_id),
                "updated_at": _now(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )


def get_party(party_id: str) -> dict | None:
    return _db()[PARTY_COLLECTION].find_one({"_id": party_id})


def get_party_by_message(message_id: int) -> dict | None:
    return _db()[PARTY_COLLECTION].find_one({"message_id": int(message_id)})


def list_active_parties(day: str) -> list[dict]:
    return list(
        _db()[PARTY_COLLECTION]
        .find(
            {
                "date": day,
                "status": {"$in": ACTIVE_STATUSES},
            }
        )
        .sort("created_at", 1)
    )


def find_active_party_by_leader(day: str, user_id: int) -> dict | None:
    return _db()[PARTY_COLLECTION].find_one(
        {
            "date": day,
            "status": {"$in": ACTIVE_STATUSES},
            "leader_id": int(user_id),
        }
    )


def find_active_membership(day: str, user_id: int) -> dict | None:
    return _db()[PARTY_COLLECTION].find_one(
        {
            "date": day,
            "status": {"$in": ACTIVE_STATUSES},
            "members": int(user_id),
        }
    )


def request_join(
    party_id: str,
    user_id: int,
    gear_snapshot: dict,
) -> dict | None:
    uid = int(user_id)
    return _db()[PARTY_COLLECTION].find_one_and_update(
        {
            "_id": party_id,
            "status": "searching",
            "members": {"$ne": uid},
            "pending": {"$ne": uid},
        },
        {
            "$addToSet": {"pending": uid},
            "$pull": {"declined": uid},
            "$set": {
                f"gear_snapshots.{uid}": dict(gear_snapshot or {}),
                "updated_at": _now(),
            },
        },
        return_document=ReturnDocument.AFTER,
    )


def withdraw_or_decline(party_id: str, user_id: int) -> dict | None:
    uid = int(user_id)
    return _db()[PARTY_COLLECTION].find_one_and_update(
        {
            "_id": party_id,
            "status": {"$in": ACTIVE_STATUSES},
            "leader_id": {"$ne": uid},
        },
        {
            "$pull": {
                "pending": uid,
                "members": uid,
            },
            "$addToSet": {"declined": uid},
            "$set": {"updated_at": _now()},
        },
        return_document=ReturnDocument.AFTER,
    )


def approve_member(
    party_id: str,
    leader_id: int,
    user_id: int,
    gear_snapshot: dict,
) -> dict | None:
    uid = int(user_id)
    return _db()[PARTY_COLLECTION].find_one_and_update(
        {
            "_id": party_id,
            "leader_id": int(leader_id),
            "status": {"$in": ACTIVE_STATUSES},
            "pending": uid,
            "members": {"$ne": uid},
            "$expr": {
                "$lt": [
                    {"$size": {"$ifNull": ["$members", []]}},
                    5,
                ]
            },
        },
        {
            "$pull": {"pending": uid},
            "$addToSet": {"members": uid},
            "$set": {
                f"gear_snapshots.{uid}": dict(gear_snapshot or {}),
                "updated_at": _now(),
            },
        },
        return_document=ReturnDocument.AFTER,
    )


def reject_member(
    party_id: str,
    leader_id: int,
    user_id: int,
) -> dict | None:
    uid = int(user_id)
    return _db()[PARTY_COLLECTION].find_one_and_update(
        {
            "_id": party_id,
            "status": {"$in": ACTIVE_STATUSES},
            "leader_id": int(leader_id),
            "pending": uid,
        },
        {
            "$pull": {"pending": uid},
            "$addToSet": {"declined": uid},
            "$set": {"updated_at": _now()},
        },
        return_document=ReturnDocument.AFTER,
    )


def remove_member(
    party_id: str,
    leader_id: int,
    user_id: int,
) -> dict | None:
    uid = int(user_id)
    return _db()[PARTY_COLLECTION].find_one_and_update(
        {
            "_id": party_id,
            "status": {"$in": ACTIVE_STATUSES},
            "$and": [
                {"leader_id": int(leader_id)},
                {"leader_id": {"$ne": uid}},
            ],
            "members": uid,
        },
        {
            "$pull": {"members": uid},
            "$set": {"updated_at": _now()},
        },
        return_document=ReturnDocument.AFTER,
    )


def replace_member(
    party_id: str,
    leader_id: int,
    old_user_id: int,
    new_user_id: int,
    gear_snapshot: dict,
) -> dict | None:
    old_uid = int(old_user_id)
    new_uid = int(new_user_id)

    if old_uid == int(leader_id):
        return None

    return _db()[PARTY_COLLECTION].find_one_and_update(
        {
            "_id": party_id,
            "status": {"$in": ACTIVE_STATUSES},
            "leader_id": int(leader_id),
            "$and": [
                {"members": old_uid},
                {"members": {"$ne": new_uid}},
            ],
            "pending": new_uid,
        },
        {
            "$pull": {
                "members": old_uid,
                "pending": new_uid,
            },
            "$addToSet": {"members": new_uid},
            "$set": {
                f"gear_snapshots.{new_uid}": dict(gear_snapshot or {}),
                "updated_at": _now(),
            },
        },
        return_document=ReturnDocument.AFTER,
    )


def transfer_leader(
    party_id: str,
    old_leader_id: int,
    new_leader_id: int,
) -> dict | None:
    return _db()[PARTY_COLLECTION].find_one_and_update(
        {
            "_id": party_id,
            "status": {"$in": ACTIVE_STATUSES},
            "leader_id": int(old_leader_id),
            "members": int(new_leader_id),
        },
        {
            "$set": {
                "leader_id": int(new_leader_id),
                "updated_at": _now(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )


def edit_party(
    party_id: str,
    leader_id: int,
    *,
    activity: str,
    time_text: str,
    notes: str,
) -> dict | None:
    return _db()[PARTY_COLLECTION].find_one_and_update(
        {
            "_id": party_id,
            "status": {"$in": ACTIVE_STATUSES},
            "leader_id": int(leader_id),
        },
        {
            "$set": {
                "activity": activity.strip() or "Black Shrine",
                "time_text": time_text.strip() or "Не вказано",
                "notes": notes.strip(),
                "updated_at": _now(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )


def toggle_search(
    party_id: str,
    leader_id: int,
) -> dict | None:
    collection = _db()[PARTY_COLLECTION]
    party = collection.find_one(
        {
            "_id": party_id,
            "leader_id": int(leader_id),
            "status": {"$in": ACTIVE_STATUSES},
        }
    )
    if not party:
        return None

    new_status = "closed" if party.get("status") == "searching" else "searching"
    return collection.find_one_and_update(
        {
            "_id": party_id,
            "leader_id": int(leader_id),
            "status": party.get("status"),
        },
        {
            "$set": {
                "status": new_status,
                "updated_at": _now(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )


def complete_party(
    party_id: str,
    leader_id: int,
) -> dict | None:
    return _db()[PARTY_COLLECTION].find_one_and_update(
        {
            "_id": party_id,
            "leader_id": int(leader_id),
            "status": {"$in": ACTIVE_STATUSES},
        },
        {
            "$set": {
                "status": "completed",
                "completed_at": _now(),
                "updated_at": _now(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )


def remove_pending_from_other_parties(
    day: str,
    user_id: int,
    keep_party_id: str,
) -> None:
    _db()[PARTY_COLLECTION].update_many(
        {
            "date": day,
            "_id": {"$ne": keep_party_id},
            "status": {"$in": ACTIVE_STATUSES},
            "pending": int(user_id),
        },
        {
            "$pull": {"pending": int(user_id)},
            "$set": {"updated_at": _now()},
        },
    )
