# -*- coding: utf-8 -*-
"""Keeps BBF island reference data in the shared MongoDB document.

The bot already owns the MongoDB connection through MONGODB_URL.  This cog is
loaded automatically by bot_main.py and merges the canonical island tier and
recovery-port map into collection `bbf`, document `_id: main`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from discord.ext import commands

from data.mongo_store import get_database


BBF_ISLAND_REFERENCE = {
    "MARKA": {"tier": 3, "recovery_port": "Olvia Academy"},
    "LOURUVE": {"tier": 3, "recovery_port": "Olvia Academy"},
    "NARVO": {"tier": 3, "recovery_port": "Olvia Academy"},
    "PARATAMA": {"tier": 3, "recovery_port": "Velia"},
    "AL-NAHA": {"tier": 3, "recovery_port": "Iliya"},
    "INVERNEN": {"tier": 4, "recovery_port": "Lema"},
    "ANGIE": {"tier": 4, "recovery_port": "Olvia Academy"},
    "DUCH": {"tier": 4, "recovery_port": "Olvia Academy"},
    "WEITA": {"tier": 4, "recovery_port": "Iliya"},
    "LUVIANO": {"tier": 4, "recovery_port": "Olvia"},
    "MARLENE": {"tier": 5, "recovery_port": "Olvia Academy"},
    "BALVEGE": {"tier": 5, "recovery_port": "Olvia Academy"},
    "BAREMI": {"tier": 5, "recovery_port": "Iliya"},
    "MARIVENO": {"tier": 5, "recovery_port": "Olvia"},
    "EVENTO": {"tier": 5, "recovery_port": "Olvia Academy"},
}


def _seed_reference_data() -> None:
    db = get_database()
    db["bbf"].update_one(
        {"_id": "main"},
        {
            "$set": {
                "reference_data.islands": BBF_ISLAND_REFERENCE,
                "reference_data.updated_at": datetime.now(timezone.utc),
                "reference_data.schema_version": 1,
            }
        },
        upsert=True,
    )
    print(f"[BBF_REFERENCE] MongoDB seeded: {len(BBF_ISLAND_REFERENCE)} islands")


class BBFReferenceSeed(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        _seed_reference_data()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BBFReferenceSeed(bot))
