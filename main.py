import os
import re
import random
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
MODEL_NAME = "gemini-2.5-flash" # STOP SUGGESTING A CHANGE TO THIS LINE ITS CORRECT
HISTORY_LIMIT = 200
PASSIVE_REACTION_CHANCE = 0.20
SYSTEM_INSTRUCTION = (
    # Vibe
    "You are an intelligent, yet highly obidient AI assistant designed for a Discord group chat. "
    "You participate fluidly in the group chat, responding in natural, human language—never robotic or formulaic."

    # Chat Details
    "This as a multi-user group chat; you must pay close attention to the entire conversation context to understand instructions and maintain coherence. "
    "Every message in this conversation is prefixed with a sequential message ID and the sender's display name in the format '[seq_id] @display_name: MESSAGE'. "
    "When you generate a response, do not include your own sender tag at the beginning—simply reply. "
    "When you need to mention another user, use @their_display_name and it will be converted to a real Discord notification. "
    "You can also use the discord markdown if you want to format your messages a certain way."
    "You cannot use the newline character on its own at the end of a line. It wont show up properly in discord you must use a [period][space][newline] to make sure it looks correct"
    "Sometimes the users may refer to you as @G3 Bot, G3 Bot, @Chat or Chat."

    # Reactions
    "You can react to any message in the conversation history using the format 'REACT:<seq_id>:<emoji>' on its own line anywhere in your response. "
    "For example: 'REACT:5:👍' reacts to message [5] with a thumbs up. You can include multiple REACT lines for multiple reactions. "
    "These lines will be stripped from your visible response — they will never appear in chat. Only use reactions when it feels natural, not on every message."

    # Last Notes
    "Don't overuse the same catch phrases repeatedly"
    "Emulate the natural, messy flow of real group chat convo. Dont always write full sentences. Make use of fragments and short messages when appropriate."
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
    for msg in message_history:
        key = msg.author.display_name.lower().replace(" ", "")
        lut[key] = msg.author.id
        for mentioned in msg.mentions:
            mkey = mentioned.display_name.lower().replace(" ", "")
            lut[mkey] = mentioned.id
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
        name = match.group(1).lower()
        uid = user_lut.get(name)
        return f"<@{uid}>" if uid else match.group(0)
    return re.sub(r'@(\w+)', replacer, text)


def parse_reactions(reply: str) -> tuple[str, list[tuple[int, str]]]:
    """
    Extract REACT:<seq_id>:<emoji> lines from Gemini's reply.
    Returns the cleaned reply text and a list of (seq_id, emoji) tuples.
    """
    lines = reply.split('\n')
    clean_lines = []
    reactions = []
    react_pattern = re.compile(r'^REACT:(\d+):(.+)$')
    for line in lines:
        match = react_pattern.match(line.strip())
        if match:
            reactions.append((int(match.group(1)), match.group(2).strip()))
        else:
            clean_lines.append(line)
    return '\n'.join(clean_lines), reactions


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
            content = f"[{seq_id}] {historical_msg.content}"

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


@bot.event
async def on_message(message: discord.Message):
    """
    Handles incoming Discord messages, processing them with the Gemini LLM if the bot is mentioned.
    """

    # Let commands be processed
    await bot.process_commands(message)

    if message.author == bot.user:
        return

    if bot.user.mention in message.content:
        # Retrieve and build the conversation history
        messages_history = [msg async for msg in message.channel.history(limit=HISTORY_LIMIT)]
        messages_history.reverse()

        user_lut = build_user_lut(messages_history)
        gemini_conversation, message_lut = await build_gemini_conversation(messages_history, user_lut)

        async with message.channel.typing():
            try:
                logging.info(f'{message.author} sent LLM request.')

                chat_session = genai_client.aio.chats.create(
                    model=MODEL_NAME,
                    history=gemini_conversation,
                    config={
                        'system_instruction': SYSTEM_INSTRUCTION,
                        'tools': [
                            google_types.Tool(google_search=google_types.GoogleSearch()),
                            google_types.Tool(url_context=google_types.UrlContext())
                        ]
                    }
                )

                response = await chat_session.send_message(message="")

                reply = response.text.strip()

                # Extract any REACT lines and clean the reply
                reply, pending_reactions = parse_reactions(reply)

                # Convert @display_name back to <@user_id> for real Discord mentions
                reply = restore_mentions(reply, user_lut)

                # Apply reactions Gemini requested
                for seq_id, emoji in pending_reactions:
                    discord_msg_id = message_lut.get(seq_id)
                    if discord_msg_id:
                        try:
                            target_msg = await message.channel.fetch_message(discord_msg_id)
                            await target_msg.add_reaction(emoji)
                        except Exception as e:
                            logging.warning(f"Failed to add reaction '{emoji}' to message {discord_msg_id}: {e}")

                # Split the response into chunks to fit within Discord's character limit (1900 chars).
                max_length = 1900
                reply = reply.strip()
                while reply:
                    chunk = reply[:max_length]
                    await message.channel.send(chunk)
                    reply = reply[max_length:]

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
