import discord
from discord.ext import commands
from discord import app_commands

class SyncCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[DEBUG] SyncCog ініціалізовано")

    @app_commands.command(name="sync", description="Синхронізувати слеш-команди")
    @app_commands.describe(mode="Режим: 'local' тільки для цього сервера, 'global' — для всіх")
    async def sync(self, interaction: discord.Interaction, mode: str = "local"):
        print(f"[DEBUG] Виконано команду /sync (mode={mode}) від {interaction.user} (ID={interaction.user.id})")

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "🚫 Тільки адміністратори можуть синхронізувати команди.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            if mode.lower() == "global":
                print("[DEBUG] Виконуємо tree.sync() глобально")
                synced = await self.bot.tree.sync()
                msg = f"🌍 Глобально синхронізовано {len(synced)} команд."
            else:
                print(f"[DEBUG] Виконуємо tree.sync() локально для {interaction.guild.id}")
                synced = await self.bot.tree.sync(guild=interaction.guild)
                msg = f"🏠 Локально синхронізовано {len(synced)} команд для сервера {interaction.guild.name} ({interaction.guild.id})."

            print(f"[DEBUG] Отримано {len(synced)} команд: {[cmd.name for cmd in synced]}")
            await interaction.followup.send(msg, ephemeral=True)

        except Exception as e:
            print(f"[DEBUG] ❌ Помилка під час sync: {e}")
            await interaction.followup.send(f"❌ Помилка sync: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    print("[DEBUG] Завантаження SyncCog...")
    await bot.add_cog(SyncCog(bot))
    print("[DEBUG] ✅ SyncCog підвантажено")