import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import subprocess
import logging
import re
from pathlib import Path

PAPER_V2_API = "https://api.papermc.io/v2/projects/paper"
PAPER_V3_API = "https://fill.papermc.io/v3/projects/paper"
USER_AGENT = "joseph-server-updater/1.0 (jfghanimah@gmail.com)"
MC_DIR = Path("/home/joseph/minecraft_server")
START_SH = MC_DIR / "start.sh"
NOTIFY_CHANNEL_ID = 1179950256440483920


class MinecraftCog(commands.Cog, name="MinecraftCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pending_update: dict | None = None
        self.paper_update_check.start()

    def cog_unload(self):
        self.paper_update_check.cancel()

    def _get_current(self) -> tuple[str, int] | None:
        match = re.search(r'-jar\s+paper-([\d.]+)-(\d+)\.jar', START_SH.read_text())
        return (match.group(1), int(match.group(2))) if match else None

    def _get_current_jar(self) -> str | None:
        match = re.search(r'-jar\s+(paper-[\w.-]+\.jar)', START_SH.read_text())
        return match.group(1) if match else None

    async def _fetch_latest_v3(self, session: aiohttp.ClientSession) -> dict | None:
        """Fetch latest Paper build from the v3 API (covers 26.x+)."""
        headers = {"User-Agent": USER_AGENT}
        async with session.get(f"{PAPER_V3_API}/versions", headers=headers) as r:
            if r.status != 200:
                return None
            data = await r.json()

        versions = [v for v in data.get("versions", [])
                    if re.match(r'^\d+(\.\d+){1,2}$', v["version"]["id"])
                    and v["version"]["support"]["status"] == "SUPPORTED"]
        if not versions:
            return None
        latest_version = versions[0]["version"]["id"]

        async with session.get(f"{PAPER_V3_API}/versions/{latest_version}/builds", headers=headers) as r:
            if r.status != 200:
                return None
            builds = await r.json()

        if not builds:
            return None
        best = max(builds, key=lambda b: b["id"])
        dl = best["downloads"]["server:default"]
        return {
            "version": latest_version,
            "build": best["id"],
            "jar": dl["name"],
            "url": dl["url"],
        }

    async def _fetch_latest_v2(self, session: aiohttp.ClientSession) -> dict | None:
        """Fetch latest Paper build from the v2 API (covers 1.x versions)."""
        async with session.get(PAPER_V2_API) as r:
            if r.status != 200:
                return None
            data = await r.json()

        versions = [v for v in data.get("versions", []) if re.match(r'^\d+(\.\d+){1,2}$', v)]
        if not versions:
            return None
        latest_version = versions[-1]

        async with session.get(f"{PAPER_V2_API}/versions/{latest_version}/builds") as r:
            if r.status != 200:
                return None
            data = await r.json()

        builds = data.get("builds", [])
        if not builds:
            return None
        best = max(builds, key=lambda b: b["build"])
        build_num = best["build"]
        jar_name = f"paper-{latest_version}-{build_num}.jar"
        return {
            "version": latest_version,
            "build": build_num,
            "jar": jar_name,
            "url": f"{PAPER_V2_API}/versions/{latest_version}/builds/{build_num}/downloads/{jar_name}",
        }

    async def _fetch_latest(self, session: aiohttp.ClientSession) -> dict | None:
        latest = await self._fetch_latest_v3(session)
        if not latest:
            latest = await self._fetch_latest_v2(session)
        return latest

    def _is_outdated(self, current_version: str, current_build: int, latest: dict) -> bool:
        if current_version != latest["version"]:
            return True
        return latest["build"] > current_build

    @tasks.loop(hours=24)
    async def paper_update_check(self):
        channel = self.bot.get_channel(NOTIFY_CHANNEL_ID)
        if not channel:
            logging.warning("Notify channel not found — skipping Paper update check.")
            return

        async with aiohttp.ClientSession() as session:
            latest = await self._fetch_latest(session)
        if not latest:
            logging.warning("Failed to fetch latest Paper version.")
            return

        current = self._get_current()
        if not current:
            logging.warning("Could not parse current jar from start.sh.")
            return
        current_version, current_build = current

        if not self._is_outdated(current_version, current_build, latest):
            logging.info(f"Paper up to date: paper-{current_version}-{current_build}.jar (API latest: {latest['build']})")
            return

        self.pending_update = latest
        await channel.send(
            f"**Paper update available!**\n"
            f"Current: `paper-{current_version}-{current_build}.jar`\n"
            f"Latest: `{latest['jar']}`\n"
            f"Use `/mc_update` to apply it."
        )

    @paper_update_check.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="mc_update", description="Apply the latest Paper server update")
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_update(self, interaction: discord.Interaction):
        await interaction.response.defer()

        async with aiohttp.ClientSession() as session:
            latest = await self._fetch_latest(session)

        if not latest:
            await interaction.followup.send("Could not reach PaperMC API.")
            return

        current = self._get_current()
        if not current:
            await interaction.followup.send("Could not parse current jar from start.sh.")
            return
        current_version, current_build = current
        current_jar = self._get_current_jar()

        if not self._is_outdated(current_version, current_build, latest):
            await interaction.followup.send(f"Already on the latest build: `{current_jar}`")
            return

        await interaction.followup.send(f"Downloading `{latest['jar']}`...")

        dest = MC_DIR / latest["jar"]
        try:
            headers = {"User-Agent": USER_AGENT}
            async with aiohttp.ClientSession() as session:
                async with session.get(latest["url"], headers=headers) as r:
                    if r.status != 200:
                        await interaction.followup.send(f"Download failed (HTTP {r.status}).")
                        return
                    dest.write_bytes(await r.read())
        except Exception as e:
            await interaction.followup.send(f"Download error: {e}")
            return

        start_content = START_SH.read_text()
        START_SH.write_text(start_content.replace(current_jar, latest["jar"]))

        await interaction.followup.send("Restarting Minecraft server...")
        result = subprocess.run(
            ["sudo", "systemctl", "restart", "minecraft"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            await interaction.followup.send(f"Restart failed:\n```{result.stderr}```")
            return

        self.pending_update = None
        await interaction.followup.send(f"Done. Server updated to `{latest['jar']}` and restarted.")


async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftCog(bot))
