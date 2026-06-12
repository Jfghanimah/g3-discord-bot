import asyncio
import io
import logging
import re
from pathlib import Path

import discord
from discord.ext import commands, tasks
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont

# Color roles are identified purely by name convention: "#RRGGBB" (uppercase).
# No state file — anything matching this pattern is considered bot-managed.
COLOR_ROLE_RE = re.compile(r'^#[0-9A-F]{6}$')
HEX_INPUT_RE = re.compile(r'^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')

HEX_PICKER_URL = "https://htmlcolorcodes.com/color-picker/"
SWEEP_INTERVAL_HOURS = 1

# The static example palette never changes, so its rendered image is cached on disk.
PALETTE_CACHE = Path(__file__).parent / ".cache" / "palette.png"

# Example hex codes for /colors — purely informational, any hex code works with /color.
PALETTE = [
    "E74C3C", "DC143C", "FA8072", "FF7F50", "E67E22", "FFD700",
    "F1C40F", "32CD32", "2ECC71", "50C878", "1ABC9C", "00FFFF",
    "87CEEB", "3498DB", "4169E1", "000080", "9B59B6", "8A2BE2",
    "FF00FF", "FF69B4", "FFC0CB", "B57EDC", "8B4513", "95A5A6",
    "FFFFFF", "010101",
]

# ── swatch image rendering ───────────────────────────────────────────
SWATCH = 34          # color box size (px)
ROW_H = 46           # vertical space per entry
PAD = 16             # outer margin
GAP = 12             # gap between swatch and label
BG = (43, 45, 49)    # Discord dark embed background
FG = (220, 221, 222)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("consola.ttf", "DejaVuSansMono.ttf", "cour.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_swatches(entries: list[tuple[str, str | None]], columns: int) -> bytes:
    """
    Render a grid of color boxes, each with a label to its right, to PNG bytes.
    `entries` is a list of (hex_code, label) — label is the text drawn beside the
    swatch (e.g. "#FF5733" or "#FF5733  3 members"); None falls back to "#hex".
    Column width adapts to the widest label so nothing is clipped.
    """
    font = _load_font(20)
    labels = [label if label is not None else f"#{hex_code}" for hex_code, label in entries]

    # Size columns to the widest label in this batch
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    label_w = max((measure.textlength(text, font=font) for text in labels), default=0)
    col_w = SWATCH + GAP + int(label_w) + PAD

    rows = (len(entries) + columns - 1) // columns
    width = columns * col_w + PAD
    height = rows * ROW_H + PAD

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    for i, ((hex_code, _), text) in enumerate(zip(entries, labels)):
        col, row = i % columns, i // columns
        x = PAD + col * col_w
        y = PAD + row * ROW_H
        rgb = tuple(int(hex_code[j:j + 2], 16) for j in (0, 2, 4))
        # Outline keeps near-background swatches (e.g. black, white) visible
        draw.rectangle([x, y, x + SWATCH, y + SWATCH], fill=rgb, outline=FG, width=1)
        draw.text((x + SWATCH + GAP, y + SWATCH / 2), text, font=font, fill=FG, anchor="lm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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
            # Place the role directly beneath the bot's own role, which is the
            # divider for the color band (staff above the bot, group roles below
            # the colors). Use edit_role_positions, NOT role.edit(position=...):
            # the latter computes the move from the local role cache, which is
            # stale right after create_role (Discord shifts other roles
            # server-side before the gateway reconciles), so it silently leaves
            # the new role at the bottom. edit_role_positions sends the target
            # straight to Discord and lets the server reorder authoritatively.
            try:
                await guild.edit_role_positions({role: max(guild.me.top_role.position - 1, 1)})
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
            app_commands.Choice(name=f"#{hex_code}", value=hex_code)
            for hex_code in PALETTE
            if query in hex_code.lower()
        ]
        return matches[:25]

    def _palette_png(self) -> bytes:
        """The example palette never changes — render once, then serve from disk cache."""
        if PALETTE_CACHE.exists():
            return PALETTE_CACHE.read_bytes()
        png = render_swatches([(hex_code, None) for hex_code in PALETTE], columns=3)
        PALETTE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PALETTE_CACHE.write_bytes(png)
        return png

    @app_commands.command(name="colors", description="List registered colors and a palette of example hex codes.")
    async def colors(self, interaction: discord.Interaction):
        guild = interaction.guild
        registered = sorted(self._color_roles(guild), key=lambda r: len(r.members), reverse=True)

        # Registered colors change as people pick them, so render on demand.
        if registered:
            entries = [
                (r.name.lstrip("#"), f"#{r.name.lstrip('#')}   {len(r.members)} member{'s' if len(r.members) != 1 else ''}")
                for r in registered
            ]
            reg_png = await asyncio.to_thread(render_swatches, entries, 1 if len(entries) <= 8 else 2)
            registered_file = discord.File(io.BytesIO(reg_png), filename="registered.png")
        else:
            registered_file = None

        palette_png = await asyncio.to_thread(self._palette_png)
        palette_file = discord.File(io.BytesIO(palette_png), filename="palette.png")

        reg_embed = discord.Embed(
            title="🎨 Server Colors",
            description=(
                f"Pick any color with `/color <hex>` — grab one from the examples below "
                f"or [a color picker]({HEX_PICKER_URL})."
            ),
            colour=discord.Colour.blurple()
        )
        if registered_file:
            reg_embed.add_field(name=f"Registered ({len(registered)})", value="​", inline=False)
            reg_embed.set_image(url="attachment://registered.png")
        else:
            reg_embed.add_field(name="Registered (0)", value="No colors yet — be the first!", inline=False)

        palette_embed = discord.Embed(title="Example palette", colour=discord.Colour.blurple())
        palette_embed.set_image(url="attachment://palette.png")

        files = [palette_file] + ([registered_file] if registered_file else [])
        await interaction.response.send_message(embeds=[reg_embed, palette_embed], files=files)

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
