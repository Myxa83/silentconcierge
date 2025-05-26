import discord
from discord.ext import commands
from discord import app_commands, Interaction
import json
import os

TIMEZONE_FILE = "timezones.json"
MODERATOR_ROLE_ID = 1375070910138028044  # ID ролі "Модератор"

# Попередній список таймзон
TIMEZONE_CHOICES = {
    "Америка (Східна) 🇺🇸": "America/New_York",
    "Америка (Західна) 🇺🇸": "America/Los_Angeles",
    "Лондон 🇬🇧": "Europe/London",
    "Україна 🇺🇦": "Europe/Kyiv",
    "Європа (Берлін) 🇩🇪": "Europe/Berlin",
    "Азія (Токіо) 🇯🇵": "Asia/Tokyo",
    "Азія (Шанхай) 🇨🇳": "Asia/Shanghai"
}

# Завантажити дані з файлу
def load_timezones():
    if not os.path.exists(TIMEZONE_FILE):
        return {}
    with open(TIMEZONE_FILE, "r") as f:
        return json.load(f)

# Зберегти дані у файл
def save_timezones(data):
    with open(TIMEZONE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# Отримати таймзону по user_id
def get_timezone_for_user(user_id: int):
    data = load_timezones()
    return data.get(str(user_id), "Europe/London")

class TimezoneSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=tz) for label, tz in TIMEZONE_CHOICES.items()
        ]
        super().__init__(placeholder="Оберіть свій часовий пояс...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: Interaction):
        data = load_timezones()
        data[str(interaction.user.id)] = self.values[0]
        save_timezones(data)

        try:
            await interaction.user.send(f"✅ Ваш часовий пояс встановлено: `{self.values[0]}`")
            await interaction.response.defer()  # приховати взаємодію (бо DM відправлено)
        except discord.Forbidden:
            await interaction.response.defer()

class TimezoneView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(TimezoneSelect())

class TimezoneCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Якщо модератор обирає таймзону вручну (резервна команда)
    @app_commands.command(name="set_timezone", description="Оберіть ваш часовий пояс")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_timezone(self, interaction: Interaction):
        await interaction.response.send_message("🌍 Оберіть свій часовий пояс:", view=TimezoneView(), ephemeral=True)

    @set_timezone.error
    async def timezone_error(self, interaction: Interaction, error):
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message("❌ Тільки модератори можуть встановити таймзону.", ephemeral=True)

    # Відстежуємо присвоєння ролі "Модератор"
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        before_roles = {role.id for role in before.roles}
        after_roles = {role.id for role in after.roles}

        if MODERATOR_ROLE_ID not in before_roles and MODERATOR_ROLE_ID in after_roles:
            try:
                await after.send("🌍 Ви стали модератором! Оберіть свій часовий пояс:", view=TimezoneView())
            except discord.Forbidden:
                pass  # DM заборонено, мовчимо

async def setup(bot):
    await bot.add_cog(TimezoneCog(bot))
