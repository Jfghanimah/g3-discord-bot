import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import subprocess
import logging
import re
import hashlib
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
            "sha256": dl.get("sha256"),
        }

    async def _fetch_latest_v2(self, session: aiohttp.ClientSession) -> dict | None:
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
        sha256 = best.get("downloads", {}).get("application", {}).get("sha256")
        return {
            "version": latest_version,
            "build": build_num,
            "jar": jar_name,
            "url": f"{PAPER_V2_API}/versions/{latest_version}/builds/{build_num}/downloads/{jar_name}",
            "sha256": sha256,
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

    async def _apply_update(self, latest: dict) -> tuple[bool, str]:
        """Download, verify SHA256, swap jar in start.sh, restart service."""
        current_jar = self._get_current_jar()
        dest = MC_DIR / latest["jar"]

        try:
            headers = {"User-Agent": USER_AGENT}
            async with aiohttp.ClientSession() as session:
                async with session.get(latest["url"], headers=headers) as r:
                    if r.status != 200:
                        return False, f"Download failed (HTTP {r.status})."
                    data = await r.read()
        except Exception as e:
            return False, f"Download error: {e}"

        if latest.get("sha256"):
            actual = hashlib.sha256(data).hexdigest()
            if actual != latest["sha256"]:
                return False, f"Checksum mismatch — aborting. Expected `{latest['sha256']}`, got `{actual}`."

        dest.write_bytes(data)
        START_SH.write_text(START_SH.read_text().replace(current_jar, latest["jar"]))

        result = subprocess.run(
            ["sudo", "systemctl", "restart", "minecraft"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return False, f"Restart failed:\n```{result.stderr}```"

        return True, f"Updated to `{latest['jar']}`."

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
            logging.info(f"Paper up to date: paper-{current_version}-{current_build}.jar")
            return

        success, msg = await self._apply_update(latest)
        if not success:
            await channel.send(f"**Paper auto-update failed.** {msg}")

    @paper_update_check.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="mc_update", description="Force apply the latest Paper server update")
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

        if not self._is_outdated(current_version, current_build, latest):
            await interaction.followup.send(f"Already on the latest build: `{self._get_current_jar()}`")
            return

        await interaction.followup.send(f"Applying `{latest['jar']}`...")
        success, msg = await self._apply_update(latest)
        await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftCog(bot))
