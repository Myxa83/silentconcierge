import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import aiocron
import datetime
import time

# Шляхи до файлів
HISTORY_FILE = "data/garmoth_history.json"
REPORT_FILE = "data/shrine_weekly_report.json"
BG_IMAGE = "https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/a8b01adbd7a20240828071624343.jpg?raw=true"

# --- Утиліти ---

def get_gs_from_history(user_id):
    """Бере останній ГС з файлу історії Garmoth"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
            user_data = history.get(str(user_id))
            if user_data and len(user_data) > 0:
                last_entry = user_data[-1] 
                return f"{last_entry.get('ap', '??')}/{last_entry.get('dp', '??')}"
    return "??/??"

async def update_report(user_id, display_name, **kwargs):
    """Оновлює дані у звіті"""
    if not os.path.exists("data"): os.makedirs("data")
    data = []
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, "r", encoding="utf-8") as f: data = json.load(f)

    user_found = False
    for entry in data:
        if entry.get('user_id') == user_id:
            entry.update(kwargs)
            entry['last_update'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            user_found = True
            break
    
    if not user_found:
        new_entry = {
            "user_id": user_id,
            "name": display_name,
            "status": "active",
            "bosses_done": 0,
            "vacation_until": None,
            "schedule": "Не вказано",
            "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        new_entry.update(kwargs)
        data.append(new_entry)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- Модальні вікна (Введення даних) ---

class BossCountModal(discord.ui.Modal, title="Кількість босів"):
    count = discord.ui.TextInput(label="Скільки закрито (1-5)", placeholder="5", min_length=1, max_length=1)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.count.value)
            await update_report(interaction.user.id, interaction.user.display_name, bosses_done=val)
            await interaction.response.send_message(f"✅ Записано босів: {val}", ephemeral=True)
        except:
            await interaction.response.send_message("Введіть число!", ephemeral=True)

class VacationModal(discord.ui.Modal, title="Відпустка"):
    until = discord.ui.TextInput(label="До якої дати? (РРРР-ММ-ДД)", placeholder="2026-03-01")
    async def on_submit(self, interaction: discord.Interaction):
        await update_report(interaction.user.id, interaction.user.display_name, status="vacation", vacation_until=self.until.value)
        await interaction.response.send_message(f"🌴 Відпустку записано до {self.until.value}", ephemeral=True)

class ScheduleModal(discord.ui.Modal, title="Графік"):
    time_input = discord.ui.TextInput(label="Коли будете (ЧЧ:ММ)", placeholder="19:30")
    async def on_submit(self, interaction: discord.Interaction):
        try:
            today = datetime.date.today()
            dt = datetime.datetime.strptime(f"{today} {self.time_input.value}", "%Y-%m-%d %H:%M")
            ts = int(dt.timestamp())
            discord_time = f"<t:{ts}:t>" # Формат Discord для таймзон
            await update_report(interaction.user.id, interaction.user.display_name, schedule=discord_time)
            await interaction.response.send_message(f"✅ Графік: {discord_time}", ephemeral=True)
        except:
            await interaction.response.send_message("Невірний формат часу.", ephemeral=True)

# --- Кнопки в ДМ ---

class DMResponseView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Мій GS", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def gs(self, interaction: discord.Interaction, b: discord.ui.Button):
        current = get_gs_from_history(interaction.user.id)
        await update_report(interaction.user.id, interaction.user.display_name, gs_cache=current)
        await interaction.response.send_message(f"🔄 Оновлено ГС: {current}", ephemeral=True)

    @discord.ui.button(label="Графік", style=discord.ButtonStyle.secondary, emoji="⏳")
    async def sched(self, interaction: discord.Interaction, b: discord.ui.Button):
        await interaction.response.send_modal(ScheduleModal())

    @discord.ui.button(label="Пропуск", style=discord.ButtonStyle.danger, emoji="❌")
    async def skip(self, interaction: discord.Interaction, b: discord.ui.Button):
        await update_report(interaction.user.id, interaction.user.display_name, status="skip")
        await interaction.response.send_message("Сьогодні не турбую!", ephemeral=True)

    @discord.ui.button(label="Відпустка", style=discord.ButtonStyle.secondary, emoji="🌴")
    async def vacation(self, interaction: discord.Interaction, b: discord.ui.Button):
        await interaction.response.send_modal(VacationModal())

    @discord.ui.button(label="Боси", style=discord.ButtonStyle.success, emoji="🛑")
    async def bosses(self, interaction: discord.Interaction, b: discord.ui.Button):
        await interaction.response.send_modal(BossCountModal())

# --- Основний модуль ---

class ShrineSurvey(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_id = 1406569206815658077
        self.thread_id = 1358443998603120824
        # Розклад
        aiocron.crontab('0 9 * * *', func=self.send_dm_survey)
        aiocron.crontab('0 15 * * *', func=self.send_dm_survey)
        aiocron.crontab('0 0 * * 6', func=self.weekly_reset) # Субота 00:00 CET

    async def weekly_reset(self):
        """Скидання босів щотижня"""
        if os.path.exists(REPORT_FILE):
            with open(REPORT_FILE, "r", encoding="utf-8") as f: reports = json.load(f)
            today = datetime.date.today().strftime("%Y-%m-%d")
            for r in reports:
                r['bosses_done'] = 0
                if r.get('vacation_until') and r['vacation_until'] < today:
                    r['status'] = 'active'
            with open(REPORT_FILE, "w", encoding="utf-8") as f:
                json.dump(reports, f, indent=4, ensure_ascii=False)

    async def send_dm_survey(self):
        guild = self.bot.guilds[0]
        role = guild.get_role(self.role_id)
        today = datetime.date.today().strftime("%Y-%m-%d")
        
        with open(REPORT_FILE, "r", encoding="utf-8") as f: reports = json.load(f)

        for m in role.members:
            user_report = next((r for r in reports if r.get('user_id') == m.id), None)
            
            # Фільтри розсилки
            if user_report:
                if user_report.get('bosses_done', 0) >= 5: continue
                if user_report.get('status') == 'vacation' and user_report.get('vacation_until', '') >= today: continue
            
            gs = get_gs_from_history(m.id)
            done = user_report.get('bosses_done', 0) if user_report else 0
            
            embed = discord.Embed(
                title="Вітаю! Нагадування Black Shrine",
                description=f"Ваш GS: **{gs}**\nЗалишилось: **{5 - done}** босів\n\nКоли Вам буде комфортно пройти босів сьогодні?",
                color=discord.Color.from_rgb(0, 255, 191)
            )
            embed.set_footer(text="Silent Concierge | В пошуках страждущих")
            try: await m.send(embed=embed, view=DMResponseView())
            except: pass

    @app_commands.command(name="shrine_test", description="Тест розсилки та звіту")
    async def shrine_test(self, interaction: discord.Interaction):
        await interaction.response.send_message("🚀 Тест запущено!", ephemeral=True)
        await self.send_dm_survey()
        # Тут можна викликати публікацію звіту в канал

async def setup(bot):
    await bot.add_cog(ShrineSurvey(bot))
