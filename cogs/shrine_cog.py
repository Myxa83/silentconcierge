import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

# Шляхи до файлів
DATA_PATH = Path("data/shrine_queue.json")
WEEKLY_PATH = Path("data/shrine_weekly.json")
LOG_PATH = Path("logs/shrine_events.json")

class ShrineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_id = 1406569206815658077 # Роль Страждущі
        self.check_loop.start() # Запуск фонового циклу

    def cog_unload(self):
        self.check_loop.cancel()

    # --- ДОПОМІЖНІ ФУНКЦІЇ ---
    def load_data(self, path):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def save_data(self, data, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def log_event(self, message):
        logs = self.load_data(LOG_PATH) if LOG_PATH.exists() else []
        logs.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": message
        })
        self.save_data(logs[-500:], LOG_PATH)

    # --- ФОНОВІ ЗАВДАННЯ ---
    @tasks.loop(minutes=1)
    async def check_loop(self):
        now = datetime.now().strftime("%H:%M")
        today = datetime.now().weekday() # 5 - це субота

        # 09:00 - Ранкове опитування
        if now == "09:00":
            await self.send_dm_polls(is_saturday=(today == 5))

        # 15:00 - Повторне опитування
        if now == "15:00":
            await self.send_dm_polls(reminder=True)

        # 15:15 - Загальний звіт у канал
        if now == "15:15":
            await self.post_daily_report()

        # Персональні нагадування за 30 хв
        await self.check_reminders()

    # --- ЛОГІКА РОЗСИЛОК ---
    async def send_dm_polls(self, reminder=False, is_saturday=False):
        guild = self.bot.guilds[0] # Бот має бути на 1 сервері
        role = guild.get_role(self.role_id)
        weekly = self.load_data(WEEKLY_PATH)
        queue = self.load_data(DATA_PATH)

        text = "Привіт! Коли плануєш йти на Black Shrine сьогодні?"
        if is_saturday:
            text = "🚨 Сьогодні ОСТАННІЙ ДЕНЬ циклу! Коли закриєш босів?"
        if reminder:
            text = "Нагадую: ти ще не записався(лася) у список на сьогодні!"

        for member in role.members:
            user_id = str(member.id)
            # Пишемо тільки тим, у кого < 5 босів і хто ще не записаний сьогодні
            if weekly.get(user_id, 0) < 5 and user_id not in queue:
                try:
                    view = ShrineInteractionView(user_id, self)
                    await member.send(text, view=view)
                except:
                    continue

    async def check_reminders(self):
        queue = self.load_data(DATA_PATH)
        now = datetime.now()
        updated = False

        for uid, info in queue.items():
            if info.get("reminded"): continue
            
            try:
                target_time = datetime.strptime(info["time"], "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
                if now >= (target_time - timedelta(minutes=30)):
                    user = await self.bot.fetch_user(int(uid))
                    await user.send(f"⏰ Нагадую: Шрайни через 30 хвилин ({info['time']})! Готуйся.")
                    info["reminded"] = True
                    updated = True
            except:
                continue
        
        if updated: self.save_data(queue, DATA_PATH)

# --- ІНТЕРФЕЙС (КНОПКИ ТА МЕНЮ) ---
class ShrineInteractionView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="Записатись", style=discord.ButtonStyle.green)
    async def signup(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Тут відкривається Modal для введення часу та боса
        await interaction.response.send_modal(SignupModal(self.cog))

    @discord.ui.button(label="Я вже пройшов(ла)", style=discord.ButtonStyle.grey)
    async def mark_done(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = DoneDropdownView(self.user_id, self.cog)
        await interaction.response.send_message("Скільки босів ти вже закрив(ла) на цьому тижні?", view=view, ephemeral=True)

# (Тут мають бути класи SignupModal та DoneDropdownView для повної обробки)
