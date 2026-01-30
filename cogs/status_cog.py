# -*- coding: utf-8 -*-
import json
import random
import discord
from discord.ext import commands, tasks
from datetime import datetime
from pathlib import Path

# Вказуємо шлях до файлу в папці config
BASE_DIR = Path(__file__).resolve().parents[1]
STATUS_JSON_PATH = BASE_DIR / "config" / "status_phrases.json"

class StatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Запуск циклу оновлення
        self.status_updater.start()

    def cog_unload(self):
        self.status_updater.cancel()

    @tasks.loop(minutes=15)
    async def status_updater(self):
        """Оновлює статус бота, вибираючи фразу з JSON залежно від часу доби"""
        try:
            if not STATUS_JSON_PATH.exists():
                print(f"[STATUS_ERR] Файл не знайдено за шляхом: {STATUS_JSON_PATH}")
                return

            with open(STATUS_JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Визначаємо поточну годину (Київ UTC+2)
            hour = (datetime.utcnow().hour + 2) % 24
            
            # Вибір списку фраз згідно зі структурою твого JSON
            if 6 <= hour < 22:
                phrases = data.get("day_phrases", [])
                mode = "ДЕНЬ"
            else:
                phrases = data.get("night_phrases", [])
                mode = "НІЧ"

            if phrases:
                new_status = random.choice(phrases)
                # Встановлюємо активність "Грає в..."
                await self.bot.change_presence(activity=discord.Game(name=new_status))
                print(f"[STATUS][{mode}] Новий статус: {new_status}")
            else:
                print(f"[STATUS][WARN] Список фраз для '{mode}' порожній у JSON")

        except Exception as e:
            print(f"[STATUS_CRITICAL] Помилка: {e}")

    @status_updater.before_loop
    async def before_status_updater(self):
        # Чекаємо повної готовності бота перед початком циклу
        await self.bot.wait_until_ready()
        print("[STATUS] Система статусів активована.")

async def setup(bot: commands.Bot):
    await bot.add_cog(StatusCog(bot))
