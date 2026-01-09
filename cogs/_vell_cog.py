import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import pytz
import requests
from bs4 import BeautifulSoup
import re

DEFAULT_TZ = "Europe/Berlin"
AVAILABLE_TZS = [
    "Europe/London",
    "Europe/Berlin",
    "Europe/Kyiv",
    "Europe/Paris",
    "Europe/Madrid",
    "Asia/Tokyo",
    "America/New_York",
    "America/Los_Angeles"
]

class TimezoneView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        for tz in AVAILABLE_TZS:
            self.add_item(TimezoneButton(tz, cog))

class TimezoneButton(discord.ui.Button):
    def __init__(self, timezone, cog):
        super().__init__(label=timezone, style=discord.ButtonStyle.secondary, custom_id=f"tz_{timezone}")
        self.timezone = timezone
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        self.cog.vell_config["timezone"] = self.timezone
        await interaction.response.send_message(f"🌍 Часовий пояс встановлено на `{self.timezone}`", ephemeral=True)

class VellDMView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Редагувати", style=discord.ButtonStyle.primary, custom_id="vell_edit")
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        print(f"[Interaction] {interaction.user} натиснув Редагувати")
        try:
            modal = VellEditModal(self.cog)
            await interaction.response.send_modal(modal)
        except Exception as e:
            print(f"[Interaction Error] Не вдалося надіслати модальне вікно: {e}")
            await interaction.response.send_message("⚠️ Виникла помилка при відкритті модального вікна.", ephemeral=True)

    @discord.ui.button(label="Підтвердити", style=discord.ButtonStyle.success, custom_id="vell_confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        print(f"[Interaction] {interaction.user} натиснув Підтвердити")
        self.cog.vell_config["cancelled"] = False
        await interaction.response.send_message("✅ Інформацію підтверджено!", ephemeral=True)

    @discord.ui.button(label="❌ Скасувати автопост", style=discord.ButtonStyle.danger, custom_id="vell_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        print(f"[Interaction] {interaction.user} натиснув Скасувати")
        self.cog.vell_config["cancelled"] = True
        await interaction.response.send_message("🚫 Автопостинг Велла скасовано.", ephemeral=True)

class VellEditModal(discord.ui.Modal, title="🛠️ Редагування автопосту Vell"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog

        self.responsible = discord.ui.TextInput(label="🔴 Відповідальний", default="Myxa", max_length=45)
        self.departure_time = discord.ui.TextInput(label="🕓 Час відпливу (HH:MM, локальний)", default=self.calculate_default_departure_time(), max_length=10)
        self.ctg = discord.ui.TextInput(label="✅ CTG буде за 5 хвилин до Велла", default="Так", max_length=30)
        self.place = discord.ui.TextInput(label="⚓ Звідки вирушаємо", default="Око Окілу", max_length=30)

        self.add_item(self.responsible)
        self.add_item(self.departure_time)
        self.add_item(self.ctg)
        self.add_item(self.place)

    def calculate_default_departure_time(self):
        try:
            response = requests.get("https://garmoth.com/boss-timer")
            soup = BeautifulSoup(response.text, 'html.parser')
            script_tags = soup.find_all("script")
            for script in script_tags:
                if 'Vell' in script.text and 'spawnTime' in script.text:
                    match = re.search(r'spawnTime\s*:\s*"(\d{2}):(\d{2})"', script.text)
                    if match:
                        hour = int(match.group(1))
                        minute = int(match.group(2)) - 15
                        if minute < 0:
                            hour -= 1
                            minute += 60
                        return f"{hour:02d}:{minute:02d}"
        except Exception as e:
            print("[Error] Визначення часу за замовчуванням не вдалося:", e)

        day_of_week = datetime.now(pytz.timezone(DEFAULT_TZ)).weekday()
        if day_of_week == 6:
            return "15:45"
        elif day_of_week == 2:
            return "18:45"
        return "20:00"

    async def on_submit(self, interaction: discord.Interaction):
        self.cog.vell_config["responsible"] = self.responsible.value
        self.cog.vell_config["ctg"] = self.ctg.value
        self.cog.vell_config["place"] = self.place.value

        tz_value = self.cog.vell_config.get("timezone", DEFAULT_TZ)

        try:
            now = datetime.now()
            user_input_time = datetime.strptime(self.departure_time.value, "%H:%M")
            local_dt = user_input_time.replace(year=now.year, month=now.month, day=now.day)
            tz = pytz.timezone(tz_value)
            localized = tz.localize(local_dt)
            timestamp = int(localized.timestamp())
            self.cog.vell_config["departure_timestamp"] = timestamp
        except Exception as e:
            self.cog.vell_config["departure_timestamp"] = None
            print("Error parsing departure time:", e)

        await interaction.response.send_message("✅ Інформацію оновлено!", ephemeral=True)

class VellReminder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.vell_config = {
            "responsible": "Myxa",
            "server": "Valencia",
            "departure_timestamp": None,
            "ctg": "Так",
            "place": "Око Окілу",
            "cancelled": False,
            "timezone": DEFAULT_TZ
        }
        self.channel_id = 1361710729182314646
        self.moderator_role_id = 1375070910138028044
        self.dm_sent = False
        self.post_sent = False
        self.final_sent = False
        print("[VellReminder] Ініціалізація...")
        self.check_vell_event.start()

    def get_vell_spawn_time(self):
        return (22, 28)

    @tasks.loop(seconds=30)
    async def check_vell_event(self):
        print("[VellReminder] Перевірка стану події...")
        if self.vell_config.get("cancelled"):
            return

        tz = pytz.timezone("Europe/London")
        now = datetime.now(tz)

        spawn_hour, spawn_minute = self.get_vell_spawn_time()
        spawn_time = now.replace(hour=spawn_hour, minute=spawn_minute, second=0, microsecond=0)

        dm_time = now.replace(hour=4, minute=0, second=0, microsecond=0)
        post_time = now.replace(hour=4, minute=5, second=0, microsecond=0)
        final_time = now.replace(hour=4, minute=10, second=0, microsecond=0)

        if now >= dm_time and not self.dm_sent:
            self.dm_sent = True
            print("[DEBUG] Надсилання DM модераторам...")
            embed = discord.Embed(description="Перевірте інформацію перед автопостом Vell.")
            embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
            view = VellDMView(self)
            channel = self.bot.get_channel(self.channel_id)
            guild = channel.guild
            role = guild.get_role(self.moderator_role_id)
            for member in role.members:
                try:
                    await member.send(embed=embed, view=view)
                    await member.send("🌍 Встановіть ваш часовий пояс:", view=TimezoneView(self))
                except:
                    pass

        if now >= post_time and not self.post_sent:
            self.post_sent = True
            print("[DEBUG] Надсилання бірюзового ембеду")
            vell_timestamp = int(spawn_time.timestamp())
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
            self.vell_embed_msg = await self.bot.get_channel(self.channel_id).send(embed=embed)

        if now >= final_time and not self.final_sent:
            self.final_sent = True
            print("[DEBUG] Надсилання червоного ембеду")
            if hasattr(self, "vell_embed_msg"):
                embed_final = discord.Embed(
                    title="Платун на Велла з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
                    color=discord.Color.from_str("#fc0303")
                )
                embed_final.set_image(url="https://github.com/Myxa83/silentconcierge/blob/main/Vell1.png")
                embed_final.set_footer(text="Silent Concierge by Myxa | Таранька вже померла", icon_url=self.bot.user.display_avatar.url)
                await self.vell_embed_msg.edit(embed=embed_final)

async def setup(bot):
    cog = VellReminder(bot)
    await bot.add_cog(cog)
    bot.add_view(VellDMView(cog))
    bot.add_view(TimezoneView(cog))
