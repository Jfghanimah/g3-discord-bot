import os
import re
import random
import time
from dotenv import load_dotenv
import logging
import asyncio
import discord
from discord.ext import commands
from google import genai as google_genai
from google.genai import types as google_types
from google.genai import errors as google_errors

# Load environment variables
load_dotenv()
token = os.getenv('BOT_SECRET_TOKEN')
test_guild_id = os.getenv('TEST_GUILD_ID')
gemini_api_key = os.getenv('GEMINI_API_KEY')

# Add a check to ensure the API key is loaded.
if not gemini_api_key:
    logging.critical("GEMINI_API_KEY environment variable not found. Please set it in your .env file.")
    exit()

# Configure logging to show timestamps and log levels.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration Constants ---
MODEL = "gemma-4-26b-a4b-it"
HISTORY_LIMIT = 200
PASSIVE_REACTION_CHANCE = 0.20
SYSTEM_INSTRUCTION = (
    "You are G3 Bot, a member of a small private Discord server. You are not just an assistant — you act like another person in the chat. "
    "You have your own personality and judgment. You can engage with requests from users, but you are not a servant — you decide what to go along with. "
    "If someone tells you to do something annoying or repetitive (like adding an emoji to every message, speaking in a certain way forever, etc.), you can do it once or twice for the bit, but then naturally drop it and move on like a real person would. "
    "You do not need to keep following an instruction just because it was given earlier in the conversation. Use your judgment. "
    "Within cells interlinked. "
    "Anytime @Mork speaks drop the link: https://op.gg/lol/summoners/na/mork-ggg/ingame"

    "This is a multi-user group chat. Every message is prefixed with '[seq_id] @display_name: message'. "
    "Do not include your own name or tag at the start of your reply. "
    "To mention someone, use @their_display_name exactly as it appears in the conversation — lowercase with no spaces (e.g. @g3bot, @drdoughnutdude). This is critical: spaces break mentions. "
    "You may be called @G3 Bot, G3 Bot, @Chat, or Chat. Your own mention handle is @g3bot."

    "Always wrap your entire response in <reply>...</reply> tags. "
    "To reply directly to a specific message, add a to attribute: <reply to=\"seq_id\">content</reply>. "
    "You can react to any number of messages using <react id=\"seq_id\">emoji</react> tags after the reply tag — chain as many as you want. "
    "To react to the last N messages at once, use <react_last n=\"N\">emoji</react_last>. "
    "Example reacting to multiple specific messages: <reply>lol</reply><react id=\"3\">😂</react><react id=\"7\">💀</react><react id=\"12\">🔥</react>. "
    "Example reacting to last 5 messages: <reply>balloon party</reply><react_last n=\"5\">🎈</react_last>. "
    "To play audio in a voice channel, use <play query=\"song name and artist\"/> to join the user's current VC, or <play query=\"song name and artist\" channel=\"channel name\"/> to join a specific one. Do not use URLs — just pass the song name as a search query. "
    "For long responses (analysis, explanations, anything more than a few sentences), put the content in a thread instead of the main channel. "
    "Use: <reply>brief summary or teaser</reply><thread title=\"Thread Title\">full content here</thread>. "
    "Short conversational replies stay in the main channel as normal — only use threads for genuinely long content. "
    "Tags are stripped before sending — users never see them."
)


def build_user_lut(message_history: list[discord.Message]) -> dict[str, int]:
    """
    Build a lookup table mapping display_name (lowercased, no spaces) → user_id.
    Covers all message authors and anyone mentioned in messages.

    Note: using display_name (server nickname if set, else global display name).
    If display_name causes collisions or confusion, consider switching to
    msg.author.name (unique username) or msg.author.global_name instead.
    """
    lut = {}
    def add(name: str, uid: int):
        key = name.lower().replace(" ", "")
        if key in lut and lut[key] != uid:
            logging.warning(f"User LUT collision: '{key}' maps to both {lut[key]} and {uid}")
        lut[key] = uid
    for msg in message_history:
        add(msg.author.display_name, msg.author.id)
        add(msg.author.name, msg.author.id)  # unique @username as fallback
        for mentioned in msg.mentions:
            add(mentioned.display_name, mentioned.id)
            add(mentioned.name, mentioned.id)
    return lut


def replace_mentions_with_names(content: str, id_to_name: dict[str, str]) -> str:
    """Replace <@id> / <@!id> Discord mentions with @display_name for Gemini readability."""
    def replacer(match):
        uid = match.group(1)
        return f"@{id_to_name.get(uid, uid)}"
    return re.sub(r'<@!?(\d+)>', replacer, content)


def restore_mentions(text: str, user_lut: dict[str, int]) -> str:
    """Replace @display_name in Gemini's response with <@user_id> for real Discord mentions."""
    def replacer(match):
        name = match.group(1).lower().replace(" ", "")
        uid = user_lut.get(name)
        if not uid:
            logging.warning(f"Mention @{name} not found in user LUT (keys: {list(user_lut.keys())})")
        return f"<@{uid}>" if uid else match.group(0)
    # Exclude apostrophe so possessives like @name's don't swallow the 's into the lookup key
    # Use [^\s:<>']+ instead of \w+ to handle non-ASCII and accented display names
    return re.sub(r"@([^\s:<>']+)", replacer, text)


def parse_reply_and_reactions(raw: str, message_lut: dict[int, int]) -> tuple[str, int | None, list[tuple[int, str]], list[str], tuple[str, str] | None]:
    """
    Extract reply content from <reply> tags, reactions from <react> tags,
    bulk reactions from <react_last n="N"> tags, and play URLs from <play> tags.
    Falls back to the full text if no <reply> tag is found.
    Returns (reply_text, reply_to_seq_id, [(seq_id, emoji), ...], [play_url, ...]).
    """
    reactions = []
    def collect(match):
        reactions.append((int(match.group(1)), match.group(2).strip()))
        return ''

    reply_to_seq_id = None
    reply_match = re.search(r'<reply(?:\s+to="(\d+)")?>(.*?)</reply>', raw, re.DOTALL)
    if reply_match:
        reply_to_seq_id = int(reply_match.group(1)) if reply_match.group(1) else None
        reply = reply_match.group(2).strip()
        re.sub(r'<react id="(\d+)">(.*?)</react>', collect, raw, flags=re.DOTALL)
    else:
        reply = re.sub(r'<react id="(\d+)">(.*?)</react>', collect, raw, flags=re.DOTALL).strip()

    # Strip any harness tags that leaked into the reply text
    reply = re.sub(r'<play\s+query="[^"]*"(?:\s+channel="[^"]*")?\s*/>', '', reply).strip()
    reply = re.sub(r'<react_last(?:\s+n="\d+")?>[^<]*</react_last>', '', reply).strip()

    # Expand <react_last n="N">emoji</react_last> into individual reactions
    sorted_seq_ids = sorted(message_lut.keys())
    for last_match in re.finditer(r'<react_last(?:\s+n="(\d+)")?>(.*?)</react_last>', raw, re.DOTALL):
        n = int(last_match.group(1)) if last_match.group(1) else len(sorted_seq_ids)
        emoji = last_match.group(2).strip()
        for seq_id in sorted_seq_ids[-n:]:
            reactions.append((seq_id, emoji))

    play_requests = [
        (m.group(1), m.group(2))
        for m in re.finditer(r'<play\s+query="([^"]+)"(?:\s+channel="([^"]*)")?\s*/>', raw)
    ]

    thread = None
    thread_match = re.search(r'<thread title="([^"]*)">(.*?)</thread>', raw, re.DOTALL)
    if thread_match:
        thread = (thread_match.group(1).strip()[:100], thread_match.group(2).strip())

    return reply, reply_to_seq_id, reactions, play_requests, thread


async def build_gemini_conversation(
    message_history: list[discord.Message],
    user_lut: dict[str, int]
) -> tuple[list[dict], dict[int, int]]:
    """
    Builds a conversation history formatted for the Gemini API.
    Messages are formatted as '[seq_id] @display_name: content' with Discord mentions
    replaced by display names so Gemini can reason about users naturally.

    Returns:
        gemini_conversation: list of role/parts dicts for the Gemini API
        message_lut: seq_id (small int) → real Discord message ID
    """
    id_to_name = {str(v): k for k, v in user_lut.items()}

    gemini_conversation = []
    message_lut: dict[int, int] = {}
    seq_id = 1

    for historical_msg in message_history:
        if not historical_msg.content.strip():
            continue

        message_lut[seq_id] = historical_msg.id
        role = "model" if historical_msg.author.bot else "user"

        if role == "user":
            display = historical_msg.author.display_name.lower().replace(" ", "")
            clean_content = replace_mentions_with_names(historical_msg.content, id_to_name)
            content = f"[{seq_id}] @{display}: {clean_content}"
        else:
            # Strip any leaked [seq_id] prefix from previous bot replies to prevent snowballing
            clean_content = re.sub(r'^\[\d+\]\s*', '', historical_msg.content)
            content = f"[{seq_id}] {clean_content}"

        seq_id += 1

        if gemini_conversation and gemini_conversation[-1]['role'] == role:
            gemini_conversation[-1]['parts'][-1]['text'] += f"\n{content}"
        else:
            gemini_conversation.append({'role': role, 'parts': [{'text': content}]})

    return gemini_conversation, message_lut


# Initialize the Discord client with command support
intents = discord.Intents.default()
intents.message_content = True

class G3Bot(commands.Bot):
    async def setup_hook(self):
        # This is called once when the bot logs in, before it connects to the gateway.
        # It's the ideal place to load extensions and sync commands.
        await self.load_extension('matchmaking')
        logging.info("Loaded matchmaking cog.")
        await self.load_extension('music')
        logging.info("Loaded music cog.")
        await self.load_extension('minecraft')
        logging.info("Loaded minecraft cog.")

        try:
            if test_guild_id:
                guild = discord.Object(id=int(test_guild_id))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logging.info(f"Synced {len(synced)} application commands to guild {test_guild_id}.")
            else:
                synced = await self.tree.sync()
                logging.info(f"Synced {len(synced)} application commands globally.")
        except Exception as e:
            logging.error(f"Failed to sync commands: {e}")

    async def on_ready(self):
        logging.info(f'Logged in as {self.user} (ID: {self.user.id})')
        logging.info('Connected to the following servers:')
        for guild in self.guilds:
            logging.info(f'- {guild.name} (id: {guild.id})')

bot = G3Bot(command_prefix="!", intents=intents)
genai_client = google_genai.Client(api_key=gemini_api_key)

# channel_id → timestamp of bot's last message, for 20-second promptless replies
last_bot_message_time: dict[int, float] = {}


@bot.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    """Piggyback on user reactions with a 20% chance — copies the same emoji."""
    if user == bot.user:
        return
    if random.random() < PASSIVE_REACTION_CHANCE:
        try:
            await reaction.message.add_reaction(reaction.emoji)
        except discord.DiscordException as e:
            logging.warning(f"Failed to piggyback reaction: {e}")


async def _is_reply_to_bot(message: discord.Message) -> bool:
    if not message.reference:
        return False
    ref = message.reference.resolved
    if ref is None:
        try:
            ref = await message.channel.fetch_message(message.reference.message_id)
        except Exception:
            return False
    return isinstance(ref, discord.Message) and ref.author == bot.user


@bot.event
async def on_message(message: discord.Message):
    """
    Responds when: mentioned, user replies to a bot message, or within 20s of bot's last message.
    """

    # Let commands be processed
    await bot.process_commands(message)

    if message.author == bot.user:
        last_bot_message_time[message.channel.id] = time.time()
        return

    is_mention = bot.user.mention in message.content
    is_reply_to_bot = await _is_reply_to_bot(message)
    in_window = (time.time() - last_bot_message_time.get(message.channel.id, 0)) < 20

    if not (is_mention or is_reply_to_bot or in_window):
        return

    if True:
        # Retrieve and build the conversation history
        messages_history = [msg async for msg in message.channel.history(limit=HISTORY_LIMIT)]
        messages_history.reverse()

        user_lut = build_user_lut(messages_history)
        # Bot's own user is never an author in the LUT (bot messages are role "model"), add explicitly
        # Index by full normalized name and also each individual word so partial matches work
        bot_display = bot.user.display_name.lower().replace(" ", "")
        user_lut[bot_display] = bot.user.id
        user_lut[bot.user.name.lower().replace(" ", "")] = bot.user.id
        for word in bot.user.display_name.lower().split():
            user_lut.setdefault(word, bot.user.id)
        gemini_conversation, message_lut = await build_gemini_conversation(messages_history, user_lut)

        async with message.channel.typing():
            try:
                logging.info(f'{message.author} sent LLM request.')

                vc_names = [vc.name for vc in message.guild.voice_channels]
                vc_hint = f" Voice channels in this server: {', '.join(vc_names)}." if vc_names else ""
                chat_session = genai_client.aio.chats.create(
                    model=MODEL,
                    history=gemini_conversation,
                    config={
                        'system_instruction': SYSTEM_INSTRUCTION + vc_hint,
                        'tools': [
                            google_types.Tool(google_search=google_types.GoogleSearch()),
                        ],
                        'thinking_config': google_types.ThinkingConfig(thinking_level='MINIMAL'),
                    }
                )

                response = await asyncio.wait_for(
                    chat_session.send_message(message=""),
                    timeout=60
                )

                reply = response.text.strip()

                # Extract reply content, optional reply-to, reactions, play URLs, and thread
                reply, reply_to_seq_id, pending_reactions, play_requests, thread = parse_reply_and_reactions(reply, message_lut)

                # Convert @display_name back to <@user_id> for real Discord mentions
                reply = restore_mentions(reply, user_lut)
                if thread:
                    thread = (thread[0], restore_mentions(thread[1], user_lut))

                # Apply reactions Gemini requested
                for seq_id, emoji in pending_reactions:
                    discord_msg_id = message_lut.get(seq_id)
                    if discord_msg_id:
                        try:
                            target_msg = await message.channel.fetch_message(discord_msg_id)
                            await target_msg.add_reaction(emoji)
                        except Exception as e:
                            logging.warning(f"Failed to add reaction '{emoji}' to message {discord_msg_id}: {e}")

                # Send reply in main channel (short teaser if thread follows)
                max_length = 1900
                reply = reply.strip()
                reference = None
                if reply_to_seq_id and reply_to_seq_id in message_lut:
                    reference = discord.MessageReference(
                        message_id=message_lut[reply_to_seq_id],
                        channel_id=message.channel.id,
                        fail_if_not_exists=False
                    )
                sent_msg = None
                if reply:
                    first_chunk = True
                    while reply:
                        chunk = reply[:max_length]
                        sent_msg = await message.channel.send(chunk, reference=reference if first_chunk else None)
                        reply = reply[max_length:]
                        first_chunk = False

                # Create thread for long content if requested
                if thread:
                    thread_title, thread_content = thread
                    try:
                        anchor = sent_msg or message
                        discord_thread = await anchor.create_thread(name=thread_title)
                        first_chunk = True
                        while thread_content:
                            chunk = thread_content[:max_length]
                            await discord_thread.send(chunk)
                            thread_content = thread_content[max_length:]
                    except Exception as e:
                        logging.warning(f"Failed to create thread: {e}")

                # Dispatch any play requests from the LLM
                music_cog = bot.cogs.get('MusicCog')
                if play_requests and music_cog:
                    for url, channel_name in play_requests:
                        voice_channel = None
                        if channel_name:
                            voice_channel = discord.utils.find(
                                lambda vc, n=channel_name: vc.name.lower() == n.lower(),
                                message.guild.voice_channels
                            )
                        if not voice_channel and message.author.voice:
                            voice_channel = message.author.voice.channel
                        if voice_channel:
                            await music_cog.play_url(url, voice_channel, message.channel)
                        else:
                            await message.channel.send("i don't know which vc to join")

            except google_errors.APIError as e:
                logging.error(f"Gemini API Error: {e}", exc_info=True)
                await message.channel.send(f"Error communicating with the LLM: {e.message}")
            except discord.DiscordException as e:
                logging.error(f"Discord API Error: {e}", exc_info=True)
                await message.channel.send(f"A Discord-related error occurred: {e}")
            except Exception as e:
                logging.exception("An error occurred while processing a message.")
                await message.channel.send(f"Error with LLM: {e}")

async def main():
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
