# cogs/vitalnij_cog.py
import re
import json
import discord
from discord.ext import commands
from discord import app_commands
from pathlib import Path
from datetime import datetime

import aiohttp
from aiohttp import ClientTimeout
from bs4 import BeautifulSoup

from config.env_loader import GUILD_ID

# ==== ID каналів і ролей ====
WELCOME_CHAN = 1420430254375178280
CATEGORY_TICKETS = 1323454227816906803
ROLE_LEADER = 1323454517664157736
ROLE_MODERATOR = 1375070910138028044
ROLE_RECRUIT = 1323455304708522046
ROLE_FRIEND = 1325124628330446951
ROLE_NEWBIE = 1420436236987924572  # Новобранець

# ==== Файли даних ====
DATA_FILE = Path("data/tickets.json")
PROFILE_FILE = Path("data/profiles.json")
GUILD_TAGS_FILE = Path("data/guild_tags.json")

# ---------- утиліти ----------
def load_json(file: Path) -> dict:
    if file.exists():
        return json.loads(file.read_text(encoding="utf-8"))
    return {}

def save_json(file: Path, data: dict):
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load_guild_tags() -> dict:
    return load_json(GUILD_TAGS_FILE)

def next_ticket_number() -> int:
    data = load_json(DATA_FILE)
    num = int(data.get("last_ticket", 0)) + 1
    data["last_ticket"] = num
    save_json(DATA_FILE, data)
    return num

def sanitize_channel_name(name: str) -> str:
    base = re.sub(r"\s+", "-", name.strip())
    base = re.sub(r"[^a-zA-Z0-9\-\_]", "", base)
    base = base.lower() or "user"
    return f"ticket-{base}"[:95]

# ---------- парсер профілю ----------
async def fetch_profile(family_name: str) -> dict:
    result = {
        "family": family_name,
        "created": None,
        "guild": None,
        "guild_history": [],
        "characters": [],
        "max_level": None,
    }

    url = f"https://www.naeu.playblackdesert.com/en-us/Adventure/Profile?profileTarget={family_name}"
    try:
        timeout = ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return result
                html = await resp.text()
    except Exception:
        return result

    try:
        soup = BeautifulSoup(html, "html.parser")
        created_el = soup.select_one(".adventure__summary .text")
        if created_el:
            result["created"] = created_el.text.strip()

        guild_el = soup.select_one(".adventure__summary .guild")
        if guild_el:
            result["guild"] = guild_el.text.strip()

        chars = soup.select(".character__item")
        max_level = 0
        for ch in chars:
            name_el = ch.select_one(".character__name")
            level_el = ch.select_one(".character__level")
            if not name_el or not level_el:
                continue
            try:
                lvl = int(level_el.text.replace("Lv.", "").strip())
            except ValueError:
                continue
            result["characters"].append({"name": name_el.text.strip(), "level": lvl})
            max_level = max(max_level, lvl)
        if max_level:
            result["max_level"] = max_level
    except Exception:
        pass

    # кеш історії гільдій
    data = load_json(PROFILE_FILE)
    fam = data.get(
        family_name,
        {"family": family_name, "created": result["created"], "guild_history": []},
    )
    now = datetime.utcnow().strftime("%Y-%m-%d")

    if result["guild"]:
        last = fam["guild_history"][-1] if fam["guild_history"] else None
        if not last or last.get("guild") != result["guild"]:
            if last and last.get("to") is None:
                last["to"] = now
            fam["guild_history"].append({"guild": result["guild"], "from": now, "to": None})

    if result["created"]:
        fam["created"] = result["created"]
    if result["characters"]:
        fam["characters"] = result["characters"]
    if result["max_level"]:
        fam["max_level"] = result["max_level"]

    data[family_name] = fam
    save_json(PROFILE_FILE, data)

    result["guild_history"] = fam.get("guild_history", [])
    return result

# ---------- модалки ----------
class RecruitModal(discord.ui.Modal, title="Заявка в гільдію"):
    family_name = discord.ui.TextInput(label="Family Name", required=True)
    contact = discord.ui.TextInput(label="Як звертатися (необов'язково)", required=False, max_length=64)

    def __init__(self, cog: "VitalnijCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.create_ticket(interaction, "guild", self.family_name.value.strip(),
                                     self.contact.value.strip() if self.contact.value else None, None)

class FriendModal(discord.ui.Modal, title="Заявка друга"):
    family_name = discord.ui.TextInput(label="Family Name", required=True)
    guild_name = discord.ui.TextInput(label="Гільдія", required=True)
    contact = discord.ui.TextInput(label="Як звертатися (необов'язково)", required=False, max_length=64)

    def __init__(self, cog: "VitalnijCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.create_ticket(interaction, "friend", self.family_name.value.strip(),
                                     self.contact.value.strip() if self.contact.value else None,
                                     self.guild_name.value.strip())

# ---------- кнопки в тікет-каналі ----------
class TicketModeratorView(discord.ui.View):
    def __init__(self, member: discord.Member, ticket_type: str, family_name: str | None, input_guild: str | None):
        super().__init__(timeout=None)
        self.member = member
        self.ticket_type = ticket_type
        self.family_name = family_name
        self.input_guild = input_guild

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if any(r.id in [ROLE_LEADER, ROLE_MODERATOR] for r in interaction.user.roles):
            return True
        await interaction.response.send_message("⛔ Лише модератори/лідер можуть користуватись цими кнопками.", ephemeral=True)
        return False

    @discord.ui.button(label="Закрити тікет", style=discord.ButtonStyle.secondary)
    async def close_ticket(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.channel.delete(reason="Ticket closed")

    @discord.ui.button(label="Прийняти в гільдію", style=discord.ButtonStyle.success)
    async def accept_guild(self, interaction: discord.Interaction, _: discord.ui.Button):
        role = interaction.guild.get_role(ROLE_RECRUIT)
        if role:
            await self.member.add_roles(role, reason="Прийнято як Рекрута")
        if self.family_name:
            try:
                await self.member.edit(nick=f"[SC] {self.family_name}")
            except discord.Forbidden:
                pass
        await interaction.response.send_message("✅ Прийнято в гільдію.", ephemeral=True)

    @discord.ui.button(label="Прийняти як Друг", style=discord.ButtonStyle.primary)
    async def accept_friend(self, interaction: discord.Interaction, _: discord.ui.Button):
        role = interaction.guild.get_role(ROLE_FRIEND)
        if role:
            await self.member.add_roles(role, reason="Підтверджено як Друг")
        await interaction.response.send_message("✅ Прийнято як Друг.", ephemeral=True)

    @discord.ui.button(label="Бан", style=discord.ButtonStyle.danger)
    async def ban_user(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await self.member.ban(reason="Відмова в заявці")
            await interaction.channel.delete(reason="Бан користувача")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Не вдалося забанити користувача.", ephemeral=True)

# ---------- welcome-кнопки ----------
class WelcomeView(discord.ui.View):
    def __init__(self, cog: "VitalnijCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Я хочу в гільдію", style=discord.ButtonStyle.success)
    async def btn_guild(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(RecruitModal(self.cog))

    @discord.ui.button(label="Друг", style=discord.ButtonStyle.primary)
    async def btn_friend(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(FriendModal(self.cog))

    @discord.ui.button(label="Не визначився", style=discord.ButtonStyle.secondary)
    async def btn_guest(self, interaction: discord.Interaction, _: discord.ui.Button):
        # НЕ ховаємо канал welcome і НЕ знімаємо роль Новобранець
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            pass
        await self.cog.create_ticket(interaction, "guest", interaction.user.display_name, None, None)

# ---------- основний ког ----------
class VitalnijCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            self.bot.add_view(WelcomeView(self))
        except Exception:
            pass

    @app_commands.command(name="send_welcome", description="Надіслати welcome-ембед із кнопками")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def send_welcome(self, interaction: discord.Interaction):
        channel = self.bot.get_channel(WELCOME_CHAN)
        if not channel:
            return await interaction.response.send_message("❌ Канал із кнопками не знайдено.", ephemeral=True)

        embed = discord.Embed(
            title="Ласкаво просимо до 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲!",
            description=(
                "Ми раді тебе бачити у нас на сервері.\n"
                "Це наша Тиха Затока, в якій ми будуємо дружнє товариство і спільноту,\n"
                "яка оточує допомогою та підтримкою!\n\n"
                "Обери, з якої причини ти завітав до нас.\n\n"
                "Найкращі герої нашої гільдії змагаються, проливаючи кров за можливість поспілкуватися з тобою!\n\n"
                "Почекай ще трішки..."
            ),
            color=0x00FFFF,
        )
        embed.set_image(url="https://i.imgur.com/50jcd3X.gif")
        embed.set_footer(text="Silent Concierge by Myxa")

        await channel.send(embed=embed, view=WelcomeView(self))
        await interaction.response.send_message("📩 Ембед надіслано.", ephemeral=True)

    # створення тікета
    async def create_ticket(self, interaction: discord.Interaction, ticket_type: str,
                            family_name: str | None, contact: str | None, input_guild: str | None):
        guild: discord.Guild = interaction.guild
        member: discord.Member = interaction.user

        # ❗ Для "guest" не ховаємо welcome
        if ticket_type != "guest":
            welcome_channel = guild.get_channel(WELCOME_CHAN)
            if welcome_channel and not any(r.id in [ROLE_LEADER, ROLE_MODERATOR] for r in member.roles):
                await welcome_channel.set_permissions(member, overwrite=discord.PermissionOverwrite(view_channel=False))

        parsed = await fetch_profile(family_name or member.display_name)

        number = next_ticket_number()
        created_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        channel_name = sanitize_channel_name(family_name or member.name)
        category = guild.get_channel(CATEGORY_TICKETS)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.get_role(ROLE_LEADER): discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.get_role(ROLE_MODERATOR): discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        ticket_channel = await guild.create_text_channel(
            name=channel_name, category=category, overwrites=overwrites, reason="Новий тікет"
        )

        # збереження в JSON
        data = load_json(DATA_FILE)
        tickets = data.setdefault("tickets", {})
        tickets[str(ticket_channel.id)] = {
            "number": number,
            "member_id": member.id,
            "family": family_name,
            "contact": contact,
            "type": ticket_type,
            "input_guild": input_guild,
            "created": created_str,
        }
        data["last_ticket"] = number
        save_json(DATA_FILE, data)

        intro_text = {
            "guild": f"{member.mention} бажає долучитись до гільдії **Silent Cove**.",
            "friend": f"{member.mention} планує долучитись до сервера як **Друг**.",
            "guest": f"{member.mention} ще не визначився, але хоче подивитися нашу спільноту.",
        }[ticket_type]

        user_text = (
            f"🎫 **Номер тікета:** #{number}\n\n"
            f"**Ваші дані:**\n"
            f"- Family Name: **{family_name or member.display_name}**\n"
            f"{('- Гільдія: **' + input_guild + '**\\n') if input_guild else ''}"
            f"{('- Як звертатися: **' + contact + '**\\n') if contact else ''}\n"
            f"🕒 **Час створення:** {created_str}\n\n"
            f"{intro_text}\n\n"
            f"Ця інформація вже відправлена модераторам і буде розглянута найближчим часом."
        )

        await ticket_channel.send(user_text, view=TicketModeratorView(member, ticket_type, family_name, input_guild))

        # embed у DM модам
        embed = discord.Embed(title="📩 Новий тікет", color=discord.Color.teal())
        embed.set_author(name=f"{member} ({member.id})", icon_url=member.display_avatar.url if member.display_avatar else None)
        embed.add_field(name="Family Name (введено)", value=family_name or "—", inline=True)
        if input_guild:
            embed.add_field(name="Гільдія (введено)", value=input_guild, inline=True)
        if contact:
            embed.add_field(name="Як звертатися", value=contact, inline=True)
        embed.add_field(name="Час створення тікета", value=created_str, inline=False)
        embed.add_field(name="Дата акаунту (парсинг)", value=parsed.get("created") or "невідомо", inline=True)
        embed.add_field(name="Поточна гільдія (парсинг)", value=parsed.get("guild") or "—", inline=True)
        embed.add_field(name="Максимальний рівень", value=parsed.get("max_level") or "—", inline=True)

        if parsed.get("guild_history"):
            hist = "\n".join([f"- {h['guild']} ({h['from']} → {h.get('to','тепер')})" for h in parsed["guild_history"]])
            embed.add_field(name="Історія гільдій", value=hist, inline=False)

        recipients = set()
        for rid in (ROLE_LEADER, ROLE_MODERATOR):
            role = guild.get_role(rid)
            if role:
                recipients.update(role.members)

        for mod in recipients:
            try:
                await mod.send(embed=embed)
            except discord.Forbidden:
                pass

        try:
            await interaction.followup.send("✅ Тікет створено.", ephemeral=True)
        except discord.InteractionResponded:
            pass

# ---------- setup ----------
async def setup(bot: commands.Bot):
    await bot.add_cog(VitalnijCog(bot))