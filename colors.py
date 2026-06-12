import logging
import re

import discord
from discord.ext import commands, tasks
from discord import app_commands

# Color roles are identified purely by name convention: "#RRGGBB" (uppercase).
# No state file — anything matching this pattern is considered bot-managed.
COLOR_ROLE_RE = re.compile(r'^#[0-9A-F]{6}$')
HEX_INPUT_RE = re.compile(r'^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')

HEX_PICKER_URL = "https://htmlcolorcodes.com/color-picker/"
SWEEP_INTERVAL_HOURS = 1

# Example colors for /colors — purely informational, any hex code works with /color.
PALETTE = [
    ("Red", "E74C3C"),
    ("Crimson", "DC143C"),
    ("Salmon", "FA8072"),
    ("Coral", "FF7F50"),
    ("Orange", "E67E22"),
    ("Gold", "FFD700"),
    ("Yellow", "F1C40F"),
    ("Lime", "32CD32"),
    ("Green", "2ECC71"),
    ("Emerald", "50C878"),
    ("Teal", "1ABC9C"),
    ("Cyan", "00FFFF"),
    ("Sky Blue", "87CEEB"),
    ("Blue", "3498DB"),
    ("Royal Blue", "4169E1"),
    ("Navy", "000080"),
    ("Purple", "9B59B6"),
    ("Violet", "8A2BE2"),
    ("Magenta", "FF00FF"),
    ("Hot Pink", "FF69B4"),
    ("Pink", "FFC0CB"),
    ("Lavender", "B57EDC"),
    ("Brown", "8B4513"),
    ("Gray", "95A5A6"),
    ("White", "FFFFFF"),
    ("Black", "010101"),
]


def normalize_hex(raw: str) -> str | None:
    """
    Normalize user input to a 6-char uppercase hex string, or None if invalid.
    Accepts 3- or 6-digit hex, with or without a leading '#'.
    Pure black is nudged to 010101 because Discord treats 0x000000 as "no color".
    """
    match = HEX_INPUT_RE.match(raw.strip())
    if not match:
        return None
    hex_code = match.group(1)
    if len(hex_code) == 3:
        hex_code = ''.join(c * 2 for c in hex_code)
    hex_code = hex_code.upper()
    return "010101" if hex_code == "000000" else hex_code


class ColorsCog(commands.Cog, name="ColorsCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.color_sweep.start()

    def cog_unload(self):
        self.color_sweep.cancel()

    # ── helpers ──────────────────────────────────────────

    def _color_roles(self, guild: discord.Guild) -> list[discord.Role]:
        return [r for r in guild.roles if COLOR_ROLE_RE.match(r.name)]

    def _member_color_roles(self, member: discord.Member) -> list[discord.Role]:
        return [r for r in member.roles if COLOR_ROLE_RE.match(r.name)]

    async def _delete_if_empty(self, role: discord.Role) -> bool:
        """Delete a color role if no one has it anymore. Returns True if deleted."""
        if role.members:
            return False
        try:
            await role.delete(reason="Color role has no members")
            logging.info(f"Deleted empty color role {role.name} in {role.guild.name}")
            return True
        except discord.HTTPException as e:
            logging.warning(f"Failed to delete empty color role {role.name}: {e}")
            return False

    async def _clean_guild(self, guild: discord.Guild) -> int:
        """Delete all empty color roles the bot can manage. Returns count deleted."""
        deleted = 0
        for role in self._color_roles(guild):
            if role < guild.me.top_role and await self._delete_if_empty(role):
                deleted += 1
        return deleted

    # ── periodic sweep ───────────────────────────────────

    @tasks.loop(hours=SWEEP_INTERVAL_HOURS)
    async def color_sweep(self):
        for guild in self.bot.guilds:
            try:
                deleted = await self._clean_guild(guild)
                if deleted:
                    logging.info(f"Color sweep removed {deleted} empty role(s) in {guild.name}")
            except discord.HTTPException as e:
                logging.warning(f"Color sweep failed in {guild.name}: {e}")

    @color_sweep.before_loop
    async def before_color_sweep(self):
        await self.bot.wait_until_ready()

    # ── commands ─────────────────────────────────────────

    @app_commands.command(name="color", description="Set your name color. Any hex code works, e.g. FF5733.")
    @app_commands.describe(code="Hex color code (e.g. FF5733 or #FF5733). See /colors for ideas.")
    async def color(self, interaction: discord.Interaction, code: str):
        hex_code = normalize_hex(code)
        if hex_code is None:
            await interaction.response.send_message(
                f"`{code}` isn't a valid hex color. Use 6 hex digits like `FF5733` — "
                f"grab one from [a color picker]({HEX_PICKER_URL}) or `/colors`.",
                ephemeral=True
            )
            return

        guild = interaction.guild
        member = interaction.user
        role_name = f"#{hex_code}"

        role = discord.utils.get(guild.roles, name=role_name)
        if role is not None and role in member.roles and len(self._member_color_roles(member)) == 1:
            await interaction.response.send_message(f"You already have {role_name}.", ephemeral=True)
            return

        await interaction.response.defer()

        if role is None:
            try:
                role = await guild.create_role(
                    name=role_name,
                    colour=discord.Colour(int(hex_code, 16)),
                    reason=f"Color role requested by {member}"
                )
            except discord.HTTPException as e:
                logging.warning(f"Failed to create color role {role_name}: {e}")
                await interaction.followup.send(
                    "Couldn't create that color role — the server may be at Discord's 250-role "
                    "limit. Try picking an existing color from `/colors`."
                )
                return
            # Move it just under the bot's top role so the color isn't buried
            # beneath other colored roles. Best effort — position shuffles can fail.
            try:
                await role.edit(position=max(guild.me.top_role.position - 1, 1))
            except discord.HTTPException as e:
                logging.warning(f"Failed to position color role {role_name}: {e}")

        old_roles = [r for r in self._member_color_roles(member) if r != role]
        try:
            if role not in member.roles:
                await member.add_roles(role, reason="Color change")
            if old_roles:
                await member.remove_roles(*old_roles, reason="Color change")
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to manage your roles — my role needs to be "
                "above the color roles with **Manage Roles** enabled."
            )
            return

        for old in old_roles:
            await self._delete_if_empty(old)

        embed = discord.Embed(
            description=f"{member.mention} is now **{role_name}**",
            colour=role.colour
        )
        await interaction.followup.send(embed=embed)

    @color.autocomplete("code")
    async def color_autocomplete(self, interaction: discord.Interaction, current: str):
        query = current.lstrip("#").lower()
        matches = [
            app_commands.Choice(name=f"{name} (#{hex_code})", value=hex_code)
            for name, hex_code in PALETTE
            if query in name.lower() or query in hex_code.lower()
        ]
        return matches[:25]

    @app_commands.command(name="colors", description="List registered colors and a palette of example hex codes.")
    async def colors(self, interaction: discord.Interaction):
        guild = interaction.guild
        registered = sorted(self._color_roles(guild), key=lambda r: len(r.members), reverse=True)

        embed = discord.Embed(
            title="🎨 Server Colors",
            description=(
                f"Pick any color with `/color <hex>` — find your perfect shade with "
                f"[this color picker]({HEX_PICKER_URL})."
            ),
            colour=discord.Colour.blurple()
        )

        if registered:
            lines = [f"`{r.name}` — {len(r.members)} member{'s' if len(r.members) != 1 else ''}"
                     for r in registered]
            embed.add_field(name=f"Registered ({len(registered)})", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Registered (0)", value="No colors yet — be the first!", inline=False)

        # Palette split across inline fields to keep the embed compact
        chunk_size = (len(PALETTE) + 2) // 3
        for i in range(0, len(PALETTE), chunk_size):
            chunk = PALETTE[i:i + chunk_size]
            value = "\n".join(f"`#{hex_code}` {name}" for name, hex_code in chunk)
            embed.add_field(name="Palette" if i == 0 else "​", value=value, inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="colorclean", description="[Admin] Delete all color roles that have no members.")
    @app_commands.checks.has_permissions(administrator=True)
    async def colorclean(self, interaction: discord.Interaction):
        await interaction.response.defer()
        deleted = await self._clean_guild(interaction.guild)
        await interaction.followup.send(f"🧹 Removed {deleted} empty color role{'s' if deleted != 1 else ''}.")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        else:
            logging.error(f"Color command error: {error}", exc_info=error)
            msg = "Something went wrong with that color command."
            if interaction.response.is_done():
                await interaction.followup.send(msg)
            else:
                await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ColorsCog(bot))
