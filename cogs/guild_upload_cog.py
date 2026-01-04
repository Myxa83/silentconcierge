# -*- coding: utf-8 -*-
import os
import json
import asyncio
import discord
from discord.ext import commands
from discord import app_commands, ui
from datetime import datetime

import pytz
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# Конфіг
# ============================================================
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
DATA_FILE = os.path.join(CONFIG_DIR, "guild_status.json")

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")  # треба в .env
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "..", "credentials.json")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# ============================================================
# Допоміжні
# ============================================================
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"weeks": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_gsheet():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID)

# ============================================================
# UI елементи
# ============================================================
class WeekDateModal(ui.Modal, title="Додати дані для тижня"):
    week_number = ui.TextInput(label="Номер тижня", placeholder="Наприклад: 38", required=True)
    week_date = ui.TextInput(label="Дата (ДД.ММ.РРРР)", placeholder="Наприклад: 14.09.2025", required=True)

    def __init__(self, cog, images):
        super().__init__()
        self.cog = cog
        self.images = images

    async def on_submit(self, interaction: discord.Interaction):
        week = str(self.week_number.value).strip()
        date = str(self.week_date.value).strip()

        data = load_data()
        data["weeks"][week] = {
            "date": date,
            "images": self.images
        }
        save_data(data)

        # Запис у Google Sheets
        try:
            sh = get_gsheet()
            if week not in [ws.title for ws in sh.worksheets()]:
                sh.add_worksheet(title=week, rows="100", cols="20")
            ws = sh.worksheet(week)
            ws.update("A1", [["Date", "Images"]])
            ws.update("A2", [[date, ", ".join(self.images)]])
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Дані збережено локально, але Google Sheets не оновлено: {e}", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Дані для тижня {week} збережено та завантажено у Google Sheets!", ephemeral=True)


class UploadMoreView(ui.View):
    def __init__(self, cog, images):
        super().__init__(timeout=60)
        self.cog = cog
        self.images = images

    @ui.button(label="Додати ще скрін", style=discord.ButtonStyle.primary)
    async def add_more(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("📤 Завантаж наступний скрін (PNG/JPG)", ephemeral=True)

    @ui.button(label="Завершити", style=discord.ButtonStyle.success)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = WeekDateModal(self.cog, self.images)
        await interaction.response.send_modal(modal)

# ============================================================
# Cog
# ============================================================
class GuildUploadCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="guildstatus_upload", description="Завантажити таблицю активності (скріни)")
    async def guildstatus_upload(self, interaction: discord.Interaction, image: discord.Attachment):
        if not image.filename.lower().endswith((".png", ".jpg", ".jpeg")):
            await interaction.response.send_message("⚠️ Потрібен файл PNG/JPG.", ephemeral=True)
            return

        images = [image.filename]

        # Збереження локально
        folder = os.path.join(os.path.dirname(__file__), "..", "data", "uploads")
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, image.filename)
        await image.save(file_path)

        view = UploadMoreView(self, images)
        await interaction.response.send_message("✅ Скрін додано. Хочеш ще?", view=view, ephemeral=True)

# ============================================================
# Setup
# ============================================================
async def setup(bot: commands.Bot):
    await bot.add_cog(GuildUploadCog(bot))