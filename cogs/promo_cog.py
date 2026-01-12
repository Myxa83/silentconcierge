import discord
from discord.ext import commands
from discord import app_commands

POLOS_URL = "https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/PolosBir.gif?raw=true"
FOOTER_TEXT = "SilentConcierge by Myxa | Ласкаво просимо!"

class PromoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="promo",
        description="Опублікувати промо-пост SilentCove (ембед + футер + полоска)"
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def promo(self, interaction: discord.Interaction):
        promo_text = (
            "<a:upstars:1425637670197133444>```Гільдійні боси```<a:upstars:1425637670197133444> | "
            "<a:upstars:1425637670197133444>```Данжи```<a:upstars:1425637670197133444> | "
            "<a:upstars:1425637670197133444>```Арени```<a:upstars:1425637670197133444> | "
            "<a:upstars:1425637670197133444>```Ліга Гільдій```<a:upstars:1425637670197133444> | "
            "<a:upstars:1425637670197133444>```Груповий фарм```<a:upstars:1425637670197133444> | "
            "<a:upstars:1425637670197133444>```Море```<a:upstars:1425637670197133444>\n\n"

            "<:Deff:1448272177848913951><:Deff:1448272177848913951><:Deff:1448272177848913951><:Deff:1448272177848913951>"
            " Маніфест "
            "<:Deff:1448272177848913951><:Deff:1448272177848913951><:Deff:1448272177848913951><:Deff:1448272177848913951>\n"

            "<a:bulletpoint:1447549436137046099> Ми ще не пройшли PVE і тому\n"
            "<a:bulletpoint:1447549436137046099> Ми не міняємо людей на ітемки.\n"
            "<a:bulletpoint:1447549436137046099> Ми не шукаємо користь у присутності.\n"
            "<a:bulletpoint:1447549436137046099> У нас кожен - частина вогню, не цифра в строю.\n"
            "<a:bulletpoint:1447549436137046099> У нас можна мовчати.\n"
            "<a:bulletpoint:1447549436137046099> У нас можна бути втомленим.\n"
            "<a:bulletpoint:1447549436137046099> У нас можна не бути “на максимум” -\n"
            "бо ми не з тих, хто кричить про себе,\n"
            "ми з тих, хто поруч.\n"
            "<a:bulletpoint:1447549436137046099> Ми граємо не щоб вигравати статистику - а будувати гільдію, як дім.\n"
            "Навіть, якщо хтось знову вийде в море, не попрощавшись.\n\n"

            "<:Deff:1448272177848913951><:Deff:1448272177848913951><:Deff:1448272177848913951><:Deff:1448272177848913951>"
            " Інформація "
            "<:Deff:1448272177848913951><:Deff:1448272177848913951><:Deff:1448272177848913951><:Deff:1448272177848913951>\n\n"

            "<a:bulletpoint:1447549436137046099> Гільдійні боси без марш-броска.\n"
            "<a:bulletpoint:1447549436137046099> Ігровий паті контент.\n"
            "<a:bulletpoint:1447549436137046099> Допомога новачкам.\n"
            "<a:bulletpoint:1447549436137046099> 290+ водимо на харду.\n"
            "<a:bulletpoint:1447549436137046099> Доступ до квестів і бафів на старті.\n"
            "<a:bulletpoint:1447549436137046099> Активний, доброзичливий, дорослий діскорд.\n"
            "<a:bulletpoint:1447549436137046099> Ліга гільдій, Арена Соляри, Ред Бателфілд\n"
            "<a:bulletpoint:1447549436137046099> 2 активних склади.\n"
            "<a:bulletpoint:1447549436137046099> Нод вари, щодня.\n\n"
            "[Долучайся](https://discord.gg/SilentCove)"
        )

        embed = discord.Embed(
            description=promo_text,
            color=0x05B2B4
        )

        # Полоска внизу
        embed.set_image(url=POLOS_URL)

        # Футер з аватаркою бота
        icon_url = None
        if self.bot.user:
            icon_url = self.bot.user.display_avatar.url
        embed.set_footer(text=FOOTER_TEXT, icon_url=icon_url)

        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("Промо-пост опубліковано.", ephemeral=True)

    @promo.error
    async def promo_error(self, interaction: discord.Interaction, error: Exception):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Нема прав (треба Manage Messages).", ephemeral=True)
            return
        await interaction.response.send_message(f"Помилка: {type(error).__name__}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PromoCog(bot))
