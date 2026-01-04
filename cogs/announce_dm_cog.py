# -*- coding: utf-8 -*-
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

# ---------------- CONFIG ----------------
ROLE_ALLOWED = [
    1375070910138028044,  # Leader
    1425974196181270671,  # Officer
    1323454517664157736   # Moderator
]
FOOTER_TEXT = "Silent Concierge by Myxa"

# ----------------------------------------
class AnnounceDMCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _convert_github_link(self, url: str) -> str:
        """Конвертує GitHub blob-посилання у raw-посилання."""
        if "github.com" in url and "/blob/" in url:
            url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        return url

    # ────────────────────────────────────────────────
    @app_commands.command(
        name="announce_dm",
        description="Розіслати приватне повідомлення всім учасникам обраної ролі."
    )
    @app_commands.describe(
        role="Роль, якій потрібно відправити DM",
        text="Текст повідомлення (підтримує абзаци та декоративні розділювачі)",
        image_url="URL зображення (необов’язково, підтримує GitHub)",
        attachment="Завантажене зображення (необов’язково)"
    )
    async def announce_dm(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        text: str,
        image_url: str = None,
        attachment: discord.Attachment = None
    ):
        sender = interaction.user

        # Перевірка прав
        if not any(r.id in ROLE_ALLOWED for r in sender.roles):
            await interaction.response.send_message(
                "⛔ У вас немає прав для використання цієї команди.",
                ephemeral=True
            )
            return

        # ---------- ЕМБЕД ----------
        # Підтримує розділювачі та абзаци (через збереження форматування)
        embed = discord.Embed(
            title="📢 Оголошення",
            description=text,
            color=discord.Color.gold()
        )

        # Додаємо зображення — або через URL, або через вкладення
        if image_url:
            fixed_url = self._convert_github_link(image_url)
            if fixed_url.startswith(("http://", "https://")):
                embed.set_image(url=fixed_url)
        elif attachment:
            embed.set_image(url=attachment.url)

        # Футер — стандартний (бот)
        bot_avatar = self.bot.user.display_avatar.url if self.bot.user else None
        embed.set_footer(text=FOOTER_TEXT, icon_url=bot_avatar)

        # 🔹 Авторський блок (аватар + клікабельний нік)
        author_avatar = sender.display_avatar.url
        author_link = f"https://discord.com/users/{sender.id}"
        author_markdown = f"[{sender.display_name}]({author_link})"

        # Додаємо поле автора внизу (окремий блок)
        embed.add_field(
            name="Автор:",
            value=author_markdown,
            inline=False
        )

        # Іконка автора збоку
        embed.set_thumbnail(url=author_avatar)

        # ---------- РОЗСИЛКА ----------
        sent, failed = 0, 0
        await interaction.response.send_message(
            f"🔄 Розсилка запущена для ролі **{role.name}** ({len(role.members)} користувачів)...",
            ephemeral=True
        )

        for member in role.members:
            try:
                await member.send(embed=embed)
                sent += 1
                await asyncio.sleep(1)
            except discord.Forbidden:
                failed += 1

        await interaction.followup.send(
            f"✅ Розсилка завершена!\n📨 Успішно: **{sent}**, не вдалося: **{failed}**.",
            ephemeral=True
        )


# ---------------- SETUP -----------------
async def setup(bot: commands.Bot):
    await bot.add_cog(AnnounceDMCog(bot))