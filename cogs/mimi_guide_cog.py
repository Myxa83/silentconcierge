# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands

# 16 роздільників в один рядок (Discord не переносить, бо є пробіли)
DIV = " ".join(["<:divider:1439778304331747418>"] * 16)


class MimiGuideCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="mimi",
        description="Повний гайд по Mimi Doll (Lorca’s Night Questline, Drieghan)"
    )
    async def mimi(self, interaction: discord.Interaction):

        DOLL_IMAGE_URL = "https://i.ibb.co/0j3rr5f/mimi.png"
        EMOTE_GIF_URL = "https://i.postimg.cc/W4BzcXtH/chrome-oi-FPyy-Zo-BU.gif"

        embed = discord.Embed(
            title=" Mimi Doll — Lorca’s Legend (Night Questline, Drieghan)",
            description=(
                "Повний гайд по нічній лінії квестів у **Drieghan**, яка відкриває декоративну "
                "**Mimi Doll** та емоуцію **Sweeping While Moving**.\n"
                "Квести доступні **лише вночі (22:00–07:00 Game Time)**."
            ),
            color=0x00F6FF  # неонова бірюза
        )

        # Лялечка
        embed.set_thumbnail(url=DOLL_IMAGE_URL)

        # ---------------- ОБОВ'ЯЗКОВІ УМОВИ ----------------
        embed.add_field(
            name="Обов'язкові умови",
            value=(
                f"{DIV}\n"
                "• Пройти основну сюжетну лінію **Drieghan Main Questline**.\n"
                "• Закінчити side-chain **Legend of Aznak**.\n"
                "• Пройти **Chenga – Sherekhan Tome of Wisdom**.\n"
                "• Знайти NPC **Lorca** у **Duvencrune**.\n"
                "• Увімкнути тип квестів **Combat** у фільтрах.\n"
                "• Прийти до Lorca **вночі 22:00–07:00 GT** — вдень він НЕ дає квести."
            ),
            inline=False
        )

        # ---------------- СТАРТ ЛАНЦЮГА ----------------
        embed.add_field(
            name="Початок лінійки",
            value=(
                f"{DIV}\n"
                "• Lorca знаходиться біля центральної частини **Duvencrune**.\n"
                "• Удень він стоїть, але **не дає завдань**.\n"
                "• Квести з'являються тільки вночі.\n"
                "• Якщо квест не показується — перевір фільтри та час в грі."
            ),
            inline=False
        )

        # ---------------- КВЕСТИ ----------------
        embed.add_field(
            name="Квестова лінія",
            value=(
                f"{DIV}\n"
                "1. **The Light of the Spirit** – огляд покинутого будинку.\n"
                "2. **Combustion of Darkness** – очистити темну енергію поблизу.\n"
                "3. **Late Greetings** *(Night Only)* – взаємодія з вогнищем/алтарем.\n"
                "4. **Moving Doll** *(Night Only)* – знайти сліди Mimi (**Doll’s Eye**, **Trace**).\n"
                "5. **Silent Footsteps** – відстежити **Spirit Trace** та повернутися до Lorca."
            ),
            inline=False
        )

        # ---------------- МЕХАНІКА / ПОРАДИ ----------------
        embed.add_field(
            name="Механіка та поради",
            value=(
                f"{DIV}\n"
                "• Всі завдання — це **діалоги та взаємодія з об’єктами** (натискання **R**).\n"
                "• Немає бою, збору або складних механік.\n"
                "• Якщо на середині стало денним — просто дочекайся наступної ночі.\n"
                "• Якщо квест завис — перезайди або візьми його знову в Lorca."
            ),
            inline=False
        )

        # ---------------- ЧИ ПОТРІБНО ЩОСЬ ПРИНОСИТИ ----------------
        embed.add_field(
            name="Чи потрібно щось крафтити або приносити?",
            value=(
                f"{DIV}\n"
                "• **Ні.** Для цієї лінійки **немає** вимог на крафт або доставку предметів.\n"
                "• Усі «предмети» — це внутрішні об’єкти на землі, а не речі в інвентарі."
            ),
            inline=False
        )

        # ---------------- НАГОРОДИ ----------------
        embed.add_field(
            name="Нагороди",
            value=(
                f"{DIV}\n"
                "• **Mimi Doll** — декоративний предмет для житла.\n"
                "• **Social Action: Sweeping While Moving** — унікальна емоуція прибирання.\n"
                "• **Knowledge** про духів Drieghan.\n"
                "Лінійка проходиться **один раз на персонажа**."
            ),
            inline=False
        )

        # Гіфка емоуції внизу
        embed.set_image(url=EMOTE_GIF_URL)

        embed.set_footer(
            text="Silent Concierge by Myxa | Mimi Doll",
            icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None,
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MimiGuideCog(bot))
