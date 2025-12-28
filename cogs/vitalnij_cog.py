# -*- coding: utf-8 -*-
# cogs/vitalnij_cog.py - SilentCove VitalnijCog (без парсингу) 🌊
import json
import asyncio
import re
from datetime import datetime

import discord
from discord.ext import commands
from discord import app_commands

# ============================ IDs / CONFIG ============================
WELCOME_CHAN = 1420430254375178280
CATEGORY_TICKETS = 1323454227816906803

ROLE_LEADER = 1323454517664157736
ROLE_MODERATOR = 1375070910138028044
ROLE_RECRUIT = 1323455304708522046
ROLE_FRIEND = 1325124628330446951
ROLE_GUEST = 1325118787019866253
ROLE_NEWBIE = 1420436236987924572
ROLE_SVITOCH = 1383410423704846396

MODLOG_CHAN = 1350571574557675520

# Відомі гільдії друзів і їх теги
GUILD_TAGS = {
    "Angry Beavers": "AB",
    "Umbra": "U",
    "Ottake": "O",
    "Familiar": "Familiar",
    "Glory To Neptune": "GTN",
    "Marena": "M",
    "Vibes": "V",
    "Glory to the Hero": "GTTH",
    "MICE": "MICE",
    "Crimson Eclipse": "CE",
    "AURA": "AURA",
}


# ============================== MODALS ================================
class RecruitModal(discord.ui.Modal, title="Заявка в гільдію"):
    """Модалка для вступу в гільдію."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

        self.family = discord.ui.TextInput(
            label="Family Name",
            required=True,
        )
        self.display = discord.ui.TextInput(
            label="Як до тебе звертатися?",
            required=True,
        )
        self.guild = discord.ui.TextInput(
            label="Твоя гільдія (в грі)",
            required=False,
            placeholder="Silent Cove, Rumbling Cove, Angry Beavers, ...",
        )

        for i in (self.family, self.display, self.guild):
            self.add_item(i)

    async def on_submit(self, itx: discord.Interaction):
        await self.cog.create_ticket(
            itx,
            "guild",
            self.family.value,
            self.display.value,
            self.guild.value,
        )


class FriendModal(discord.ui.Modal, title="Дружня анкета"):
    """Модалка для тих, хто хоче бути другом гільдії."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

        self.family = discord.ui.TextInput(
            label="Family Name",
            required=True,
        )
        self.display = discord.ui.TextInput(
            label="Як до тебе звертатися?",
            required=True,
        )
        self.guild = discord.ui.TextInput(
            label="Твоя гільдія (в грі)",
            required=False,
            placeholder="Silent Cove, Angry Beavers, ...",
        )

        for i in (self.family, self.display, self.guild):
            self.add_item(i)

    async def on_submit(self, itx: discord.Interaction):
        await self.cog.create_ticket(
            itx,
            "friend",
            self.family.value,
            self.display.value,
            self.guild.value,
        )


# ========================== PUBLIC WELCOME VIEW =======================
class WelcomeView(discord.ui.View):
    """Публічний вью під вітальним повідомленням з кнопками."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Хочу в гільдію",
        style=discord.ButtonStyle.success,
        custom_id="welcome_guild",
    )
    async def g(self, itx: discord.Interaction, _):
        await itx.response.send_modal(RecruitModal(self.cog))

    @discord.ui.button(
        label="Друг",
        style=discord.ButtonStyle.primary,
        custom_id="welcome_friend",
    )
    async def f(self, itx: discord.Interaction, _):
        await itx.response.send_modal(FriendModal(self.cog))

    @discord.ui.button(
        label="Ще не визначився",
        style=discord.ButtonStyle.secondary,
        custom_id="welcome_guest",
    )
    async def s(self, itx: discord.Interaction, _):
        await self.cog.create_ticket(
            itx,
            "guest",
            itx.user.display_name,
            itx.user.display_name,
            "",
        )


# ======================= MODERATOR VIEW ==============================
class GuildSelect(discord.ui.Select):
    """Селект для вибору гільдії при прийнятті рекрута."""
    def __init__(self, cog):
        self.cog = cog

        options = [
            discord.SelectOption(label="Silent Cove", value="SC"),
            discord.SelectOption(label="Rumbling Cove", value="RC"),
        ]

        super().__init__(
            placeholder="Обери гільдію для рекрута",
            options=options,
            custom_id="guild_sel",
        )

    async def callback(self, itx: discord.Interaction):
        if not await self.cog.is_moderator(itx.user):
            return await itx.response.send_message(
                "🚫 У тебе немає прав.",
                ephemeral=True,
            )

        ch = itx.channel
        await itx.response.defer(ephemeral=True)
        await self.cog.accept_ticket(itx, ch.id, "guild", self.values[0])


class TicketModeratorView(discord.ui.View):
    """Вью для модераторів всередині тікет каналу."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(GuildSelect(cog))

    @discord.ui.button(
        label="💬 Додати друга",
        style=discord.ButtonStyle.primary,
        custom_id="mod_friend",
    )
    async def f(self, itx: discord.Interaction, _):
        if not await self.cog.is_moderator(itx.user):
            return await itx.response.send_message(
                "🚫 Немає прав.",
                ephemeral=True,
            )

        ch = itx.channel
        await itx.response.defer(ephemeral=True)
        await self.cog.accept_ticket(itx, ch.id, "friend")

    @discord.ui.button(
        label="🌫️ Додати гостя",
        style=discord.ButtonStyle.secondary,
        custom_id="mod_guest",
    )
    async def g(self, itx: discord.Interaction, _):
        if not await self.cog.is_moderator(itx.user):
            return await itx.response.send_message(
                "🚫 Немає прав.",
                ephemeral=True,
            )

        ch = itx.channel
        await itx.response.defer(ephemeral=True)
        await self.cog.accept_ticket(itx, ch.id, "guest")

    @discord.ui.button(
        label="⛔ Бан",
        style=discord.ButtonStyle.danger,
        custom_id="mod_ban",
    )
    async def b(self, itx: discord.Interaction, _):
        if not await self.cog.is_moderator(itx.user):
            return await itx.response.send_message(
                "🚫 Немає прав.",
                ephemeral=True,
            )

        ch = itx.channel
        await itx.response.defer(ephemeral=True)
        await self.cog.ban_from_ticket(itx, ch.id)


# ============================== MAIN COG ==============================
class VitalnijCog(commands.Cog):
    """Головний ког для вітального ембеда і системи тікетів."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ticket_meta: dict[int, dict] = {}
        self.guild_tags = {k.lower(): v for k, v in GUILD_TAGS.items()}

    async def is_moderator(self, user: discord.Member) -> bool:
        """Перевірка чи є користувач модератором або лідером."""
        return any(r.id in {ROLE_MODERATOR, ROLE_LEADER} for r in user.roles)

    @commands.Cog.listener()
    async def on_ready(self):
        """Реєструємо persistent views при старті бота."""
        self.bot.add_view(WelcomeView(self))
        self.bot.add_view(TicketModeratorView(self))
        print("[VitalnijCog] Persistent views reloaded")

    # ----------------- робота з метаданими тікета -----------------
    def get_ticket_meta(self, ch: discord.TextChannel) -> dict | None:
        if ch.id in self.ticket_meta:
            return self.ticket_meta[ch.id]

        if ch.topic and ch.topic.startswith("SC_TICKET:"):
            data = ch.topic[len("SC_TICKET:") :]
            try:
                meta = json.loads(data)
            except Exception:
                return None
            self.ticket_meta[ch.id] = meta
            return meta

        return None

    def set_ticket_meta(self, ch: discord.TextChannel, meta: dict) -> None:
        self.ticket_meta[ch.id] = meta
        try:
            payload = json.dumps(meta, ensure_ascii=False)
            topic = f"SC_TICKET:{payload}"
            asyncio.create_task(ch.edit(topic=topic))
        except Exception:
            pass

    def find_ticket_member(self, ch: discord.TextChannel) -> discord.Member | None:
        for target in ch.overwrites:
            if isinstance(target, discord.Member):
                return target
        return None

    # ----------------- команда для відправки вітального ембеда -----------------
    @app_commands.command(
        name="send_welcome",
        description="Надіслати вітальний ембед Silent Cove",
    )
    async def send_welcome(self, itx: discord.Interaction):
        ch = itx.guild.get_channel(WELCOME_CHAN)
        if not ch:
            return await itx.response.send_message(
                "❌ Канал не знайдено.",
                ephemeral=True,
            )

        e = discord.Embed(
            title="<a:SilentCove:1425637670197133444> · Ласкаво просимо до Silent Cove",
            description=(
                "Ми раді тебе бачити у нас на сервері.\n"
                "Це наша Тиха Затока, у якій ми будуємо\n"
                "Дружнє товариство та спільноту, яка оточує допомогою і підтримкою.\n\n"
                "Обери, з якої причини ти завітав до нас.\n\n"
                "Найкращі герої нашої гільдії змагаються,\n"
                "проливаючи кров за можливість поспілкуватися з тобою."
            ),
            color=discord.Color.dark_teal(),
        )

        e.set_footer(
            text="Silent Concierge by Myxa",
            icon_url=self.bot.user.display_avatar.url,
        )

        await ch.send(embed=e, view=WelcomeView(self))
        await itx.response.send_message(
            "✅ Надіслано вітальне повідомлення.",
            ephemeral=True,
        )

    # ----------------- створення тікета -----------------
    async def create_ticket(
        self,
        itx: discord.Interaction,
        typ: str,
        family: str,
        display: str,
        guild_name: str,
    ) -> int:
        """
        Створює закритий канал тікета для користувача.
        """
        await itx.response.defer(ephemeral=True, thinking=True)

        g = itx.guild
        m = itx.user
        cat = g.get_channel(CATEGORY_TICKETS)

        overwrites = {
            g.default_role: discord.PermissionOverwrite(view_channel=False),
            m: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            g.me: discord.PermissionOverwrite(view_channel=True),
        }

        mod_role = g.get_role(ROLE_MODERATOR)
        if mod_role:
            overwrites[mod_role] = discord.PermissionOverwrite(view_channel=True)

        ch = await g.create_text_channel(
            name=f"ticket-{m.name}",
            category=cat,
            overwrites=overwrites,
            reason="Ticket created",
        )

        meta = {
            "user_id": m.id,
            "type": typ,
            "family": family,
            "display": display,
            "guild": guild_name,
        }
        self.set_ticket_meta(ch, meta)

        info = discord.Embed(
            title=f"🎫 Заявка від {m.display_name}",
            description="Тільки модератори бачать це повідомлення.",
            color=discord.Color.teal(),
        )
        info.add_field(name="Family Name", value=family or "не вказано", inline=True)
        info.add_field(
            name="Як звертатися",
            value=display or m.display_name,
            inline=True,
        )
        if guild_name:
            info.add_field(name="Гільдія", value=guild_name, inline=False)

        await ch.send(embed=info, view=TicketModeratorView(self))

        await self.dm_ticket_to_mods(itx, ch.id, typ, family, display, guild_name)
        await self.log_ticket_created(ch, m, typ, family, display, guild_name)

        return ch.id

    # ----------------- прийняття тікета -----------------
    async def accept_ticket(
        self,
        itx: discord.Interaction,
        ch_id: int,
        mode: str,
        tag: str | None = None,
    ):
        """
        Приймає тікет в одному з режимів:
        guild, friend, guest.
        """
        g = itx.guild
        ch = g.get_channel(ch_id)
        if not ch:
            return

        member = self.find_ticket_member(ch)
        if not member:
            return

        meta = self.get_ticket_meta(ch) or {}
        family = meta.get("family") or member.display_name
        display = meta.get("display") or member.display_name
        guild_name = meta.get("guild") or ""

        family_clean = re.sub(r"[^A-Za-z0-9]+", "", family).strip()
        display_clean = display.strip() or member.display_name

        if mode == "guild":
            tag = tag or "SC"
            new_nick = f"[{tag}] {family_clean} | {display_clean}"
        else:
            new_nick = member.display_name

        nick_changed = True
        try:
            await member.edit(nick=new_nick)
        except discord.Forbidden:
            nick_changed = False
        except Exception:
            nick_changed = False

        roles_to_add_ids: list[int] = []
        roles_to_remove_ids: list[int] = []

        if mode == "guild":
            roles_to_add_ids.append(ROLE_RECRUIT)
            roles_to_add_ids.append(ROLE_SVITOCH)
            roles_to_remove_ids.extend([ROLE_NEWBIE, ROLE_GUEST])
        elif mode == "friend":
            roles_to_add_ids.append(ROLE_FRIEND)
            roles_to_remove_ids.append(ROLE_NEWBIE)
        elif mode == "guest":
            roles_to_add_ids.append(ROLE_GUEST)
            roles_to_remove_ids.append(ROLE_NEWBIE)

        role_added_ok = True
        for rid in roles_to_add_ids:
            role = g.get_role(rid)
            if not role:
                continue
            try:
                await member.add_roles(role, reason=f"Ticket accepted as {mode}")
            except discord.Forbidden:
                role_added_ok = False
            except Exception:
                role_added_ok = False

        role_removed_ok = True
        for rid in roles_to_remove_ids:
            role = g.get_role(rid)
            if not role or role not in member.roles:
                continue
            try:
                await member.remove_roles(role, reason="Ticket accepted cleanup")
            except discord.Forbidden:
                role_removed_ok = False
            except Exception:
                role_removed_ok = False

        problems: list[str] = []

        if not nick_changed and mode == "guild":
            problems.append(
                f"Не вдалося змінити нік користувача {member.mention}. Перевір права або ієрархію ролей."
            )
        if not role_added_ok:
            problems.append(
                f"Не вдалося видати одну або більше ролей для {member.mention}."
            )
        if not role_removed_ok:
            problems.append(
                f"Не вдалося прибрати одну або більше службових ролей у {member.mention}."
            )

        if problems:
            try:
                await itx.user.send("\n".join(["⚠️ " + p for p in problems]))
            except Exception:
                pass

        await self.log_ticket_accepted(ch, member, mode, tag, new_nick)

        try:
            await ch.delete(reason=f"Ticket accepted as {mode}")
        except Exception:
            pass

    # ----------------- бан з тікета -----------------
    async def ban_from_ticket(self, itx: discord.Interaction, ch_id: int):
        g = itx.guild
        ch = g.get_channel(ch_id)
        if not ch:
            return

        member = self.find_ticket_member(ch)
        if not member:
            return

        try:
            await g.ban(member, reason="Бан з тікета", delete_message_days=0)
        except discord.Forbidden:
            return await itx.followup.send(
                "Не вдалося забанити користувача. Перевір права бота.",
                ephemeral=True,
            )
        except Exception:
            return await itx.followup.send(
                "Сталася помилка при бані користувача.",
                ephemeral=True,
            )

        await self.log_ticket_banned(ch, member, itx.user)

        try:
            await ch.delete(reason="Ticket ban")
        except Exception:
            pass

        await itx.followup.send(
            f"Користувач {member.mention} забанений, тікет закрито.",
            ephemeral=True,
        )

    # ----------------- DM до модів -----------------
    async def dm_ticket_to_mods(
        self,
        itx: discord.Interaction,
        ticket_channel_id: int,
        typ: str,
        family: str,
        display: str,
        guild_name: str,
    ):
        """
        Надсилає коротке повідомлення всім модераторам.
        """
        g = itx.guild
        u = itx.user

        ts = int(datetime.utcnow().timestamp())
        tmap = {
            "guild": "🪪 Хоче вступити в гільдію",
            "friend": "💬 Хоче долучитися як друг",
            "guest": "🌫️ Ще не визначився",
        }

        e = discord.Embed(
            title=f"📨 Нова заявка • {u}",
            description=tmap.get(typ, typ),
            color=discord.Color.dark_teal(),
        )

        e.set_thumbnail(url=u.display_avatar.url)

        e.add_field(
            name="Користувач",
            value=f"{u.mention}\n`{u}`",
            inline=False,
        )

        e.add_field(
            name="Discord створено",
            value=f"<t:{int(u.created_at.timestamp())}:F>",
            inline=True,
        )
        e.add_field(
            name="Подано",
            value=f"<t:{ts}:F>",
            inline=True,
        )

        e.add_field(name="Family Name", value=family or "не вказано", inline=True)
        e.add_field(
            name="Як звертатися",
            value=display or u.display_name,
            inline=True,
        )

        if guild_name:
            tag = self.guild_tags.get(guild_name.strip().lower())
            if tag:
                guild_val = f"{guild_name} [{tag}]"
            else:
                guild_val = guild_name
            e.add_field(name="Гільдія", value=guild_val, inline=False)

        e.add_field(
            name="Посилання на тікет",
            value=f"[Відкрити](https://discord.com/channels/{g.id}/{ticket_channel_id})",
            inline=False,
        )

        e.set_footer(text="Silent Concierge. Внутрішня інформація без парсингу")

        mod_role = g.get_role(ROLE_MODERATOR)
        if not mod_role:
            return

        for mod in mod_role.members:
            try:
                await mod.send(embed=e)
            except Exception:
                pass

    # ----------------- логування в модлог -----------------
    async def log_ticket_created(
        self,
        ch: discord.TextChannel,
        member: discord.Member,
        typ: str,
        family: str,
        display: str,
        guild_name: str,
    ):
        g = ch.guild
        log_ch = g.get_channel(MODLOG_CHAN)
        if not log_ch:
            return

        e = discord.Embed(
            title="Створено новий тікет",
            description=f"Канал {ch.mention}",
            color=discord.Color.blurple(),
        )
        e.add_field(name="Користувач", value=member.mention, inline=True)
        e.add_field(name="Тип", value=typ, inline=True)
        e.add_field(name="Family", value=family or "не вказано", inline=True)
        e.add_field(
            name="Як звертатися",
            value=display or member.display_name,
            inline=True,
        )
        if guild_name:
            e.add_field(name="Гільдія", value=guild_name, inline=True)

        await log_ch.send(embed=e)

    async def log_ticket_accepted(
        self,
        ch: discord.TextChannel,
        member: discord.Member,
        mode: str,
        tag: str | None,
        new_nick: str,
    ):
        g = ch.guild
        log_ch = g.get_channel(MODLOG_CHAN)
        if not log_ch:
            return

        e = discord.Embed(
            title="Тікет прийнятий",
            description=f"Канал {ch.name} закрито",
            color=discord.Color.green(),
        )
        e.add_field(name="Користувач", value=member.mention, inline=True)
        e.add_field(name="Режим", value=mode, inline=True)
        if mode == "guild":
            e.add_field(name="Тег гільдії", value=tag or "SC", inline=True)
            e.add_field(name="Новий нік", value=new_nick, inline=False)

        await log_ch.send(embed=e)

    async def log_ticket_banned(
        self,
        ch: discord.TextChannel,
        member: discord.Member,
        moderator: discord.Member,
    ):
        g = ch.guild
        log_ch = g.get_channel(MODLOG_CHAN)
        if not log_ch:
            return

        e = discord.Embed(
            title="Бан з тікета",
            description=f"Канал {ch.name} закрито",
            color=discord.Color.red(),
        )
        e.add_field(name="Користувач", value=member.mention, inline=True)
        e.add_field(name="Модератор", value=moderator.mention, inline=True)

        await log_ch.send(embed=e)


# ============================ SETUP ==================================
async def setup(bot: commands.Bot):
    await bot.add_cog(VitalnijCog(bot))