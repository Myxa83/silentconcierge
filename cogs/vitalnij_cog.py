# -*- coding: utf-8 -*-
# cogs/vitalnij_cog.py - SilentCove VitalnijCog (без парсингу) 🌊
import json
import asyncio
import re
from datetime import datetime
from pathlib import Path

import discord
from discord.ext import commands
from discord import app_commands

# ============================ IDs / CONFIG ============================
WELCOME_CHAN = 1420430254375178280
CATEGORY_TICKETS = 1323454227816906803

ROLE_LEADER = 1323454517664157736
ROLE_MODERATOR = 1323454742965389446

ROLE_SILENT_COVE = 1323454377306327051
ROLE_RUMBLING_COVE = 1323454377339889724

ROLE_RECRUIT = 1323455304708522046
ROLE_FRIEND = 1323455304712978503
ROLE_GUEST = 1323455304708522047
ROLE_SVITOCH = 1323455304708522048
ROLE_NEWBIE = 1420436236987924572
GUILD_TAGS_PATH = Path(__file__).resolve().parents[1] / "config" / "guild_tags.json"

GUILD_TAGS = {
    "Silent Cove": "SC",
    "Rumbling Cove": "RC",
}

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
            placeholder="Обери гільдію",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="mod_guild_select",
        )

    async def callback(self, itx: discord.Interaction):
        if not await self.cog.is_moderator(itx.user):
            return await itx.response.send_message(
                "🚫 Немає прав.",
                ephemeral=True,
            )

        ch = itx.channel
        tag = self.values[0]
        await itx.response.defer(ephemeral=True)
        await self.cog.accept_ticket(itx, ch.id, "guild", tag=tag)


class ModeratorView(discord.ui.View):
    """Кнопки для модератора."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(GuildSelect(cog))

    @discord.ui.button(
        label="💬 Додати друга",
        style=discord.ButtonStyle.secondary,
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
        await self.cog.ban_ticket(itx, ch.id)

# ======================= USER VIEW ==================================
class RecruitModal(discord.ui.Modal, title="Заявка"):
    guild = discord.ui.TextInput(
        label="Твоя гільдія (в грі)",
        placeholder="Наприклад: SaxyCave",
        required=False,
        max_length=64,
    )
    family = discord.ui.TextInput(
        label="Family Name",
        placeholder="Наприклад: GOODROOT",
        required=False,
        max_length=64,
    )
    display = discord.ui.TextInput(
        label="Як до тебе звертатися",
        placeholder="Наприклад: Галя",
        required=False,
        max_length=64,
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, itx: discord.Interaction):
        await self.cog.create_ticket(
            itx,
            "guild",
            self.family.value,
            self.display.value,
            self.guild.value,
        )


class WelcomeView(discord.ui.View):
    """Кнопки для гравця."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="🪪 Хочу в гільдію",
        style=discord.ButtonStyle.success,
        custom_id="user_want_guild",
    )
    async def want_guild(self, itx: discord.Interaction, _):
        await itx.response.send_modal(RecruitModal(self.cog))

    @discord.ui.button(
        label="💬 Хочу бути другом",
        style=discord.ButtonStyle.secondary,
        custom_id="user_want_friend",
    )
    async def want_friend(self, itx: discord.Interaction, _):
        await self.cog.create_ticket(
            itx,
            "friend",
            itx.user.display_name,
            itx.user.display_name,
            "",
        )

    @discord.ui.button(
        label="🌫️ Я ще не визначився",
        style=discord.ButtonStyle.secondary,
        custom_id="user_want_guest",
    )
    async def want_guest(self, itx: discord.Interaction, _):
        await self.cog.create_ticket(
            itx,
            "guest",
            itx.user.display_name,
            itx.user.display_name,
            "",
        )

# ======================= COG ========================================
class VitalnijCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ticket_meta: dict[int, dict] = {}
        self.guild_tags = {k.lower(): v for k, v in GUILD_TAGS.items()}

    # ----------------- helpers for guild tags and nicknames -----------------
    def _cut32(self, s: str) -> str:
        s = (s or "").strip()
        return s[:32]

    def _norm_guild(self, s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"[\s\-_'.]+", "", s)
        s = re.sub(r"[^a-z0-9]+", "", s)
        return s

    def _suggest_tag(self, name: str, used: set[str]) -> str:
        name = (name or "").strip()
        words = [w for w in re.split(r"\s+", name) if w]
        base = "".join([w[0] for w in words if w])[:4].upper()
        if not base:
            base = re.sub(r"[^A-Za-z0-9]+", "", name)[:4].upper() or "TAG"

        tag = base
        i = 2
        while tag in used:
            tag = (base[:3] + str(i))[:4]
            i += 1
        return tag

    def _load_guild_tags_file(self) -> dict[str, str]:
        try:
            if not GUILD_TAGS_PATH.exists():
                return {}
            data = json.loads(GUILD_TAGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
            return {}
        except Exception:
            return {}

    def _save_guild_tags_file(self, data: dict[str, str]) -> None:
        try:
            GUILD_TAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            GUILD_TAGS_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _resolve_or_add_guild_tag(self, guild_name: str) -> tuple[str | None, dict[str, str]]:
        raw = (guild_name or "").strip()
        data = self._load_guild_tags_file()

        # fallback: include hardcoded tags too (but file wins)
        for k, v in GUILD_TAGS.items():
            if k not in data:
                data[k] = v

        if not raw:
            return None, data

        norm = self._norm_guild(raw)
        alias_to_key: dict[str, str] = {}

        for k in list(data.keys()):
            nk = self._norm_guild(k)
            if nk:
                alias_to_key[nk] = k

        if norm in alias_to_key:
            key = alias_to_key[norm]
            return str(data.get(key)), data

        used = set(str(v) for v in data.values())
        new_tag = self._suggest_tag(raw, used)
        data[raw] = new_tag

        nospace = re.sub(r"\s+", "", raw)
        if nospace and nospace != raw and nospace not in data:
            data[nospace] = new_tag

        self._save_guild_tags_file(data)
        return new_tag, data

    async def is_moderator(self, user: discord.Member) -> bool:
        """Перевірка чи є користувач модератором або лідером."""
        return any(r.id in {ROLE_MODERATOR, ROLE_LEADER} for r in user.roles)

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            self.bot.add_view(WelcomeView(self))
            self.bot.add_view(ModeratorView(self))
        except Exception:
            pass

    # ----------------- meta in topic -----------------
    def get_ticket_meta(self, ch: discord.TextChannel) -> dict | None:
        try:
            if ch.topic and ch.topic.startswith("SC_TICKET:"):
                payload = ch.topic[len("SC_TICKET:"):]
                meta = json.loads(payload)
                if isinstance(meta, dict):
                    self.ticket_meta[ch.id] = meta
                    return meta
        except Exception:
            return None

        if ch.id in self.ticket_meta:
            return self.ticket_meta[ch.id]

        return None

    def set_ticket_meta(self, ch: discord.TextChannel, meta: dict) -> None:
        self.ticket_meta[ch.id] = meta
        try:
            payload = json.dumps(meta, ensure_ascii=False)
            topic = f"SC_TICKET:{payload}"
            asyncio.create_task(ch.edit(topic=topic))
        except Exception:
            pass

    async def find_ticket_member(self, ch: discord.TextChannel) -> discord.Member | None:
        # 1) пробуємо як було: member в overwrites
        for target in ch.overwrites:
            if isinstance(target, discord.Member):
                return target

        # 2) fallback: беремо user_id з meta і fetch_member
        meta = self.get_ticket_meta(ch) or {}
        uid = meta.get("user_id")
        if uid:
            try:
                return await ch.guild.fetch_member(int(uid))
            except Exception:
                return None

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
            title="🌊 Ласкаво просимо до Silent Cove",
            description=(
                "Ти опинився в місці, де панує спокій.\n\n"
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
        g = itx.guild
        m = itx.user

        cat = g.get_channel(CATEGORY_TICKETS)
        if not cat or not isinstance(cat, discord.CategoryChannel):
            await itx.response.send_message(
                "❌ Категорію тікетів не знайдено.",
                ephemeral=True,
            )
            return 0

        ts = int(datetime.utcnow().timestamp())
        base = "ticket"
        if typ == "guild":
            base = "guild"
        elif typ == "friend":
            base = "friend"
        elif typ == "guest":
            base = "guest"

        name = f"{base}-{m.name}-{ts}"
        overwrites = {
            g.default_role: discord.PermissionOverwrite(view_channel=False),
            m: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        # моди
        for rid in [ROLE_MODERATOR, ROLE_LEADER]:
            r = g.get_role(rid)
            if r:
                overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        ch = await g.create_text_channel(
            name=name,
            category=cat,
            overwrites=overwrites,
            reason="Ticket create",
        )

        meta = {
            "typ": typ,
            "user_id": m.id,
            "family": family,
            "display": display,
            "guild": guild_name,
            "created_at": ts,
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

        await ch.send(embed=info, view=ModeratorView(self))

        await itx.response.send_message(
            "✅ Заявку створено. Модератор скоро відповість.",
            ephemeral=True,
        )

        await self.notify_mods_ticket(itx, typ, ch, family, display, guild_name)
        return ch.id

    # ----------------- прийняти тікет -----------------
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

        member = await self.find_ticket_member(ch)
        if not member:
            return

        meta = self.get_ticket_meta(ch) or {}
        family = meta.get("family") or member.display_name
        display = meta.get("display") or member.display_name
        guild_name = meta.get("guild") or ""

        family_raw = (family or "").strip()
        family_clean = re.sub(r"[^A-Za-z0-9]+", "", family_raw).strip()
        # Якщо family кирилицею або чистка дала порожньо, не вбиваємо нік
        if not family_clean:
            family_clean = family_raw or member.name

        display_clean = (display or "").strip() or member.display_name

        # Режими:
        # - guild: як було, через селект гільдії (tag)
        # - friend: тег беремо з config/guild_tags.json або додаємо новий
        # - guest: без тега
        resolved_tag: str | None = None
        if mode == "friend":
            resolved_tag, _ = self._resolve_or_add_guild_tag(guild_name)

        if mode == "guild":
            tag = tag or "SC"
            new_nick = self._cut32(f"[{tag}] {family_clean} | {display_clean}")
        elif mode == "friend":
            if resolved_tag:
                new_nick = self._cut32(f"[{resolved_tag}] {family_clean} | {display_clean}")
            else:
                new_nick = self._cut32(f"{family_clean} | {display_clean}")
        elif mode == "guest":
            new_nick = self._cut32(display_clean)
        else:
            new_nick = member.display_name

        nick_changed = True
        nick_error: str | None = None
        try:
            await member.edit(nick=new_nick, reason=f"Ticket accepted as {mode}")
        except discord.Forbidden:
            nick_changed = False
            nick_error = "Forbidden: немає прав або роль бота нижче"
        except Exception as e:
            nick_changed = False
            nick_error = f"{type(e).__name__}: {e}"

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

        if not nick_changed and mode in {"guild", "friend", "guest"}:
            problems.append(
                f"Нік не змінився для {member.mention}. Причина: {nick_error or 'невідомо'}. Спроба: `{new_nick}`"
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

            # І одразу показуємо модеру тут, щоб не загубилось в DM
            try:
                await itx.followup.send(
                    "⚠️ Проблеми:\n" + "\n".join(["- " + p for p in problems]),
                    ephemeral=True,
                )
            except Exception:
                pass
        else:
            try:
                await itx.followup.send(
                    f"✅ Прийнято як {mode}. Нік: `{new_nick}`",
                    ephemeral=True,
                )
            except Exception:
                pass

        await self.log_ticket_accepted(ch, member, mode, tag, new_nick)

        try:
            await ch.delete(reason=f"Ticket accepted as {mode}")
        except Exception:
            pass

    async def ban_ticket(self, itx: discord.Interaction, ch_id: int):
        g = itx.guild
        ch = g.get_channel(ch_id)
        if not ch:
            return

        member = await self.find_ticket_member(ch)
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

    async def notify_mods_ticket(
        self,
        itx: discord.Interaction,
        typ: str,
        ticket_ch: discord.TextChannel,
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
        title = tmap.get(typ, "🎫 Новий тікет")

        msg = (
            f"{title}\n"
            f"Користувач: {u.mention}\n"
            f"Канал: {ticket_ch.mention}\n"
            f"Час: <t:{ts}:R>\n"
        )
        if family:
            msg += f"Family: `{family}`\n"
        if display:
            msg += f"Name: `{display}`\n"
        if guild_name:
            msg += f"Guild: `{guild_name}`\n"

        # сповіщаємо по ролі модератора
        mod_role = g.get_role(ROLE_MODERATOR)
        if mod_role:
            try:
                await ticket_ch.send(mod_role.mention)
            except Exception:
                pass

        # і в сам канал
        try:
            await ticket_ch.send(msg)
        except Exception:
            pass

    # ----------------- логування -----------------
    async def log_ticket_accepted(self, ch: discord.TextChannel, member: discord.Member, mode: str, tag: str | None, new_nick: str):
        try:
            entry = {
                "action": "accepted",
                "channel_id": ch.id,
                "user_id": member.id,
                "user_display": member.display_name,
                "mode": mode,
                "tag": tag,
                "new_nick": new_nick,
                "ts": int(datetime.utcnow().timestamp()),
            }
            await self._write_log(entry)
        except Exception:
            pass

    async def log_ticket_banned(self, ch: discord.TextChannel, member: discord.Member, moderator: discord.Member):
        try:
            entry = {
                "action": "banned",
                "channel_id": ch.id,
                "user_id": member.id,
                "user_display": member.display_name,
                "moderator_id": moderator.id,
                "moderator_display": moderator.display_name,
                "ts": int(datetime.utcnow().timestamp()),
            }
            await self._write_log(entry)
        except Exception:
            pass

    async def _write_log(self, entry: dict):
        # Простий лог у файл logs/YYYY-MM-DD.json
        try:
            from pathlib import Path as _Path
            base = _Path("logs")
            base.mkdir(exist_ok=True)
            fn = base / f"{datetime.utcnow().strftime('%Y-%m-%d')}.json"

            if fn.exists():
                try:
                    data = json.loads(fn.read_text(encoding="utf-8"))
                    if not isinstance(data, list):
                        data = []
                except Exception:
                    data = []
            else:
                data = []

            data.append(entry)
            fn.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(VitalnijCog(bot))
