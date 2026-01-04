# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands

# 16 роздільників в один рядок
DIV = " ".join(["<:divider:1439778304331747418>"] * 16)

MELODY = "<:Melody:1439827099882885140>"
ALL_CREATION = "<:All_Creation:1439827191545204756>"


class AtaraxiaGuideCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[ATARAXIA] Cog ініціалізовано")

    @app_commands.command(
        name="ataraxia",
        description="Гайд: Musical Spirit Wall Lamp та квести Ataraxia's Footsteps"
    )
    async def ataraxia(self, interaction: discord.Interaction):

        embed = discord.Embed(
            title="🎶 Musical Spirit Wall Lamp & Ataraxia’s Footsteps",
            description=(
                "Дуже легкий XD рецепт виготовлення"
            ),
            color=0x00F6FF
        )

        # ---------- РЕЦЕПТ ----------
        embed.add_field(
            name="\u200b",
            value=(
                f"{DIV}\n"
                "- **Pure Nickel Crystal ×20**\n"
                "- **Shining Powder ×20**\n"
                f"- **Melody of the Stars ×15**\n"
                "- **Spirit's Leaf ×10**\n\n"
                "Але, щоб його скрафтити, треба отримати **знання** про Musical Spirit Wall Lamp.\n"
                "А щоб отримати знання — треба виконати квестову лінійку Ataraxia 🫠"
            ),
            inline=False
        )

        # ---------- СТАРТ ЛАНЦЮЖКА ----------
        embed.add_field(
            name="\u200b",
            value=(
                f"{DIV}\n"
                "**Старт ланцюжка квестів**\n"
                "Після завершення **\"[O'dyllita] The First Barbarian\"**, "
                "ви зможете прийняти новий квест у схованці **Dark Knight** в **Olun Valley**, "
                "від **Arethel of the Obsidian Ashes**.\n\n"
                "• Знайти можна у вікні квестів (**O**) у розділі **Quest Type → Combat**.\n"
                "• Сам квест перевірити: **Main → [Lv. 60 O'dyllita II] Gem of Imbalance**."
            ),
            inline=False
        )

        # ---------- ЛІНІЙКА (ЧАСТИНА 1) ----------
        embed.add_field(
            name="\u200b",
            value=(
                f"{DIV}\n"
                "**Квестова лінійка “Ataraxia's Footsteps” (1/2)**\n"
                "• Ataraxia's Travels\n"
                "• Ataraxia's Energy #1\n"
                "• Neigh Neigh's Ambush\n"
                "• The Whole Ambush\n"
                "• Sightseeing the Outside World\n"
                "• Save the Merchant\n"
                "• The Con-niving Merchant\n"
                "• Ataraxia's Energy #2\n"
                "• Kusha's Spider Silk\n"
                "• \"Improved\" Spider Silk\n"
                "• Ataraxia's Future\n"
                "• Ataraxia's Energy #3\n"
                "• First Time in the Desert\n"
                "• Giant Desert Scorpion\n"
                "• Eggs in One Basket\n"
                "• Failed Trade"
            ),
            inline=False
        )

        # ---------- ЛІНІЙКА (ЧАСТИНА 2) ----------
        embed.add_field(
            name="\u200b",
            value=(
                f"{DIV}\n"
                "**Квестова лінійка “Ataraxia's Footsteps” (2/2)**\n"
                "• Ataraxia's Energy #4\n"
                "• Valencia Inn\n"
                "• Secret of the Fig Pie\n"
                "• Ataraxia's Energy #5\n"
                "• A Dark Knight in Velia\n"
                "• Three Dogs\n"
                "• Ataraxia's Energy #6\n"
                "• Progress Report\n"
                "• Dark Knight and Wine\n"
                "• Ataraxia's Energy #7\n"
                "• Trapped Soul\n"
                "• Ataraxia's Energy #8\n"
                "• Slum Whereabouts\n"
                "• Saint of the Slum\n"
                "• Ataraxia's Influence\n"
                "• Ataraxia's Energy #9"
            ),
            inline=False
        )

        # ---------- НАГОРОДИ ----------
        embed.add_field(
            name="\u200b",
            value=(
                f"{DIV}\n"
                "**Нагороди за квестову лінійку**\n"
                "• 9 записів знань *“Ataraxia's Energy”*.\n"
                "• Титул **“Fig Pie Chef”**.\n"
                "• Квест на **Ah'krad** (раз на сім’ю).\n"
                "• Знання **Musical Spirit Wall Lamp** (раз на персонажа).\n"
                "• Можливість виготовляти матеріали через **Manufacture (L)**."
            ),
            inline=False
        )

        # ---------- MELODY OF STARS ----------
embed.add_field(
    name="\u200b",
    value=(
        f"{DIV}\n"
        f"**Як отримати Melody of Stars {MELODY}**\n"
        f"{MELODY} Отримується через **Heating** аксесуарів синьої якості.\n\n"
        "**Кількість:**\n"
        "• PRI (I): 1 шт.\n"
        "• DUO (II): 5 шт.\n"
        "• TRI (III): 25 шт."
    ),
    inline=False
)

# ---------- FRAGMENT OF ALL CREATION ----------
embed.add_field(
    name="\u200b",
    value=(
        f"{DIV}\n"
        f"**Як отримати Fragment of All Creation {ALL_CREATION}**\n"
        f"{ALL_CREATION} Створюється через **Simple Alchemy**.\n\n"
        "**Матеріали:**\n"
        "• Narc's Lightning ×100\n"
        "• Fragment of All Creation ×10\n"
        "• Legacy of the Ancient ×10"
    ),
    inline=False
)

        embed.set_footer(
            text="Silent Concierge by Myxa | Musical Spirit Wall Lamp",
            icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    print("[ATARAXIA] setup() викликано")
    await bot.add_cog(AtaraxiaGuideCog(bot))
