import io
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import View, Button
from PIL import Image, ImageDraw


class PostView(View):
    def __init__(self, options):
        super().__init__(timeout=None)
        for label in options:
            self.add_item(PostButton(label))


class PostButton(Button):
    def __init__(self, label):
        super().__init__(label=label, style=discord.ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        await interaction.response.send_message(
            f"✅ Ви обрали: **{self.label}**",
            ephemeral=True
        )


class PostCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def rounded_image_from_url(self, url: str):
        """
        Повертає (discord.File, attachment_url) або (None, None).
        НІКОЛИ не повертає одиночний None, щоб не валити unpack.
        """
        if not url:
            return None, None

        try:
            timeout = aiohttp.ClientTimeout(total=12)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None, None
                    data = await resp.read()
        except Exception as e:
            print(f"[POST] ❌ Не вдалося скачати картинку: {type(e).__name__}: {e}")
            return None, None

        try:
            image = Image.open(io.BytesIO(data)).convert("RGBA")

            w, h = image.size
            radius = 40

            mask = Image.new("L", (w, h), 0)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=255)

            out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            out.paste(image, (0, 0), mask)

            buffer = io.BytesIO()
            out.save(buffer, format="PNG")
            buffer.seek(0)

            file = discord.File(buffer, filename="rounded.png")
            return file, "attachment://rounded.png"
        except Exception as e:
            print(f"[POST] ❌ Помилка обробки зображення: {type(e).__name__}: {e}")
            return None, None

    @app_commands.command(name="пост", description="Створити допис або опитування з кнопками")
    @app_commands.describe(
        заголовок="Заголовок повідомлення",
        текст="Основний текст (markdown підтримується)",
        картинка="Посилання на зображення (буде округлене)",
        шрифт="Назва шрифту (пишеться як текст)",
        опитування1="Варіант 1",
        опитування2="Варіант 2",
        опитування3="Варіант 3",
        опитування4="Варіант 4",
        опитування5="Варіант 5",
    )
    async def пост(
        self,
        interaction: Interaction,
        заголовок: str = None,
        текст: str = None,
        картинка: str = None,
        шрифт: str = None,
        опитування1: str = None,
        опитування2: str = None,
        опитування3: str = None,
        опитування4: str = None,
        опитування5: str = None,
    ):
        # defer обовязково, інакше Discord покаже "не відповідає"
        await interaction.response.defer(ephemeral=True)

        embed = None
        file = None

        try:
            if заголовок or текст or картинка:
                embed = discord.Embed(
                    title=заголовок or "",
                    description=текст or "",
                    color=discord.Color.teal(),
                )

                if шрифт:
                    embed.set_author(name=f"Шрифт: {шрифт}")

                if картинка:
                    file, image_url = await self.rounded_image_from_url(картинка)
                    if image_url:
                        embed.set_image(url=image_url)

            options = [opt for opt in [опитування1, опитування2, опитування3, опитування4, опитування5] if opt]
            view = PostView(options) if options else None

            # Відправка: НЕ передаємо file= якщо file None
            if not embed and view:
                await interaction.followup.send("📊 Виберіть варіант:", view=view, ephemeral=False)

            elif embed and view:
                if file:
                    await interaction.followup.send(embed=embed, view=view, file=file, ephemeral=False)
                else:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=False)

            elif embed:
                if file:
                    await interaction.followup.send(embed=embed, file=file, ephemeral=False)
                else:
                    await interaction.followup.send(embed=embed, ephemeral=False)

            else:
                await interaction.followup.send("❌ Ви не заповнили жодне поле.", ephemeral=True)

        except Exception as e:
            # Щоб не було "Програма не відповідає", показуємо причину
            await interaction.followup.send(
                f"❌ Помилка в /пост: `{type(e).__name__}: {e}`",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(PostCog(bot))
