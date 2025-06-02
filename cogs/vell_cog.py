import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
from datetime import datetime, timedelta
import pytz

DEFAULT_TZ = "Europe/Berlin"

async def get_real_spawn_time():
    today = datetime.now(pytz.timezone(DEFAULT_TZ)).weekday()
    if today == 6:
        return 16, 0
    elif today == 2:
        return 19, 0
    return 3, 20

def get_next_vell_datetime():
    tz = pytz.timezone(DEFAULT_TZ)
    now = datetime.now(tz)

    next_wed = now + timedelta((2 - now.weekday()) % 7)
    next_sun = now + timedelta((6 - now.weekday()) % 7)

    next_wed_time = next_wed.replace(hour=19, minute=0, second=0, microsecond=0)
    next_sun_time = next_sun.replace(hour=16, minute=0, second=0, microsecond=0)

    if now < next_wed_time:
        return next_wed_time
    else:
        return next_sun_time

class VellPostModal(ui.Modal, title="Редагування перед постингом Велла"):
    responsible = ui.TextInput(label="Відповідальний", placeholder="Введіть ім'я", required=True)
    server = ui.TextInput(label="Сервер", placeholder="Наприклад: Кама5", required=True)
    ctg = ui.TextInput(label="CTG", placeholder="Так / Ні", required=True)
    place = ui.TextInput(label="Місце", placeholder="Око Окілу", required=True)
    test_time = ui.TextInput(label="Тестовий час (ГГ:ХХ)", placeholder="Опціонально", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("VellReminder")
        cog.vell_config["responsible"] = self.responsible.value
        cog.vell_config["server"] = self.server.value
        cog.vell_config["ctg"] = self.ctg.value
        cog.vell_config["place"] = self.place.value
        if self.test_time.value:
            try:
                hour, minute = map(int, self.test_time.value.split(":"))
                cog.vell_config["test_spawn_time"] = (hour, minute)
            except ValueError:
                pass  # Ignore wrong format silently
        embed = await cog.build_vell_embed()
        await interaction.response.defer()
        await interaction.channel.send(embed=embed)
        cog.dm_sent = True
        cog.post_sent = True

class VellReminder(commands.Cog):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        print("[DEBUG] Ініціалізація VellReminder...")
        self.vell_config = {
            "responsible": "Myxa",
            "server": "Kamasільва 5",
            "departure_timestamp": None,
            "ctg": "Так",
            "place": "Око Окілу",
            "cancelled": False,
            "timezone": DEFAULT_TZ,
            "channel_id": 1361710729182314646,
            "test_spawn_time": None
        }
        self.moderator_role_id = 1375070910138028044
        self.dm_sent = False
        self.post_sent = False
        self.final_sent = False
        self.confirmed = False

    async def build_vell_embed(self):
        print("[DEBUG] Створення основного ембеду Велла...")
        spawn_hour, spawn_minute = await get_real_spawn_time()
        if self.vell_config.get("test_spawn_time"):
            spawn_hour, spawn_minute = self.vell_config["test_spawn_time"]

        vell_time = datetime.now(pytz.timezone(self.vell_config.get("timezone", DEFAULT_TZ)))
        vell_time = vell_time.replace(hour=spawn_hour, minute=spawn_minute, second=0, microsecond=0)
        vell_timestamp = int(vell_time.timestamp())

        departure_ts = self.vell_config.get("departure_timestamp")
        embed = discord.Embed(
            title="Платун на Велла з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
            description="<:Vell:1375254921259257906> Давай з нами за серцем Велла, чи за 4 кронами <:crone:1375254950925438986>",
            color=discord.Color.teal()
        )
        embed.add_field(name="**📌 Шепотіть:**", value=f"```ansi\n\u001b[0;31m{self.vell_config['responsible']}\u001b[0m\n```", inline=False)
        embed.add_field(name="**🏝️ Сервер**", value=self.vell_config["server"], inline=False)
        embed.add_field(name="**🐙 Велл:**", value=f"<t:{vell_timestamp}:t> *(локальний час)*", inline=False)
        if departure_ts:
            embed.add_field(name="**⏰ Відпливаємо о:**", value=f"<t:{departure_ts}:t> *(локальний час)*", inline=False)
        embed.add_field(name="**✅ CTG:**", value=self.vell_config["ctg"], inline=False)
        embed.add_field(name="**⛵ Платун вирушає з:**", value=self.vell_config["place"], inline=False)
        embed.set_image(url="https://raw.githubusercontent.com/Myxa83/silentconcierge/main/raw.png")
        embed.set_footer(text="Silent Concierge by Myxa | Швидше за таранькой - пиво гріється", icon_url=self.bot.user.display_avatar.url)
        return embed

    def build_final_embed(self):
        print("[DEBUG] Створення фінального ембеду Велла...")
        embed_final = discord.Embed(
            title="Платун на Велла з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
            color=discord.Color.from_str("#fc0303")
        )
        embed_final.set_image(url="https://raw.githubusercontent.com/Myxa83/silentconcierge/main/Vell1.png")
        embed_final.set_footer(text="Silent Concierge by Myxa | Таранька вже померла", icon_url=self.bot.user.display_avatar.url)
        return embed_final

    @tasks.loop(seconds=30)
    async def check_vell_event(self):
        # ... залишилось без змін ...
        pass

    @app_commands.command(name="vellpost", description="Ручний запуск ембеду Велла")
    async def vell_post(self, interaction: discord.Interaction):
        await interaction.response.send_modal(VellPostModal())

    @app_commands.command(name="vellconfig", description="Відкрити налаштування Велла")
    async def vell_config(self, interaction: discord.Interaction):
        # ... залишилось без змін ...
        pass

async def setup(bot):
    cog = VellReminder(bot)
    await bot.add_cog(cog)
    cog.check_vell_event.start()
