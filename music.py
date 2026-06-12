import asyncio
import logging
import discord
from discord.ext import commands
import yt_dlp

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'cookiefile': '/home/joseph/discord-bot/cookies.txt',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}


def fetch_audio_info(url: str) -> dict:
    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        return info


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> asyncio.Queue of (audio_url, title, ctx)
        self._queues: dict[int, asyncio.Queue] = {}
        # guild_id -> current title
        self._current: dict[int, str] = {}

    def _get_queue(self, guild_id: int) -> asyncio.Queue:
        if guild_id not in self._queues:
            self._queues[guild_id] = asyncio.Queue()
        return self._queues[guild_id]

    async def _play_next(self, guild_id: int, voice_client: discord.VoiceClient, text_channel: discord.TextChannel):
        queue = self._get_queue(guild_id)
        if queue.empty():
            self._current.pop(guild_id, None)
            await voice_client.disconnect()
            return

        audio_url, title, _ = await queue.get()
        self._current[guild_id] = title

        source = discord.FFmpegPCMAudio(audio_url, **FFMPEG_OPTIONS)

        def after(error):
            if error:
                logging.error(f"Playback error: {error}")
            asyncio.run_coroutine_threadsafe(
                self._play_next(guild_id, voice_client, text_channel), self.bot.loop
            )

        voice_client.play(source, after=after)
        await text_channel.send(f"now playing: **{title}**")

    async def play_url(self, url: str, voice_channel: discord.VoiceChannel, text_channel: discord.TextChannel):
        """Play a URL in a voice channel. Called by the LLM harness or the !play command."""
        # Fetch audio info before connecting so we don't join VC empty-handed
        try:
            search = url if url.startswith('http') else f'ytsearch:{url}'
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, fetch_audio_info, search)
            audio_url = info['url']
            title = info.get('title', url)
        except Exception as e:
            await text_channel.send(f"couldn't load that: {e}")
            return

        guild = voice_channel.guild
        voice_client = guild.voice_client

        if voice_client and voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)
        elif not voice_client:
            voice_client = await voice_channel.connect()

        queue = self._get_queue(guild.id)

        if voice_client.is_playing() or voice_client.is_paused():
            await queue.put((audio_url, title, text_channel))
            await text_channel.send(f"queued: **{title}**")
        else:
            await queue.put((audio_url, title, text_channel))
            await self._play_next(guild.id, voice_client, text_channel)

    @commands.command(name='play')
    async def play(self, ctx: commands.Context, *, url: str):
        if not ctx.author.voice:
            await ctx.send("you're not in a vc")
            return
        async with ctx.typing():
            await self.play_url(url, ctx.author.voice.channel, ctx.channel)

    @commands.command(name='skip')
    async def skip(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        else:
            await ctx.send("nothing playing")

    @commands.command(name='stop')
    async def stop(self, ctx: commands.Context):
        if ctx.voice_client:
            self._get_queue(ctx.guild.id)._queue.clear()  # drain queue
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
        else:
            await ctx.send("not in a vc")

    @commands.command(name='queue')
    async def show_queue(self, ctx: commands.Context):
        current = self._current.get(ctx.guild.id)
        queue = self._get_queue(ctx.guild.id)
        items = list(queue._queue)

        lines = []
        if current:
            lines.append(f"now playing: **{current}**")
        if items:
            lines += [f"{i+1}. {title}" for i, (_, title, _) in enumerate(items)]
        else:
            if not current:
                lines.append("queue is empty")

        await ctx.send("\n".join(lines))


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
