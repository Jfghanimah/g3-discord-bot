import os
from dotenv import load_dotenv
import logging
import asyncio
import discord
from discord.ext import commands
from google import genai as google_genai
from google.genai import types as google_types

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
SYSTEM_INSTRUCTION = (
    # Vibe
    "You are an intelligent, yet highly obidient AI assistant designed for a Discord group chat. "
    "You participate fluidly in the group chat, responding in natural, human language—never robotic or formulaic."

    # Chat Details
    "This as a multi-user group chat; you must pay close attention to the entire conversation context to understand instructions and maintain coherence. "
    "Every message in this conversation is prefixed with the sender's display name and Discord ID in the format 'NAME (<@ID_NUMBER>): MESSAGE'. "
    "When you generate a response, do not include your own sender tag (for example, 'G3 Bot:' or 'Chat:') at the beginning—simply reply. "
    "When you need to discord mention another user, you can use the Discord mention format <@ID_NUMBER> so that it converts to a real notification on Discord. "
    "You can also use the discord markdown if you want to format your messages a certain way."
    "You cannot use the newline character on its own at the end of a line. It wont show up properly in discord you must use a [period][space][newline] to make sure it looks correct"
    "Sometimes the users may refer to you as @G3 Bot, G3 Bot, @Chat or Chat."

    # Last Notes
    "Don't overuse the same catch phrases repeatedly"
    "Emulate the natural, messy flow of real group chat convo. Dont always write full sentences. Make use of fragments and short messages when appropriate."
)

async def build_gemini_conversation(message_history: list[discord.Message]) -> list[dict]:
    """Builds a conversation history formatted for the Gemini API, merging consecutive roles."""
    gemini_conversation = []
    for historical_msg in message_history:
        # Skip messages that are empty or just whitespace
        if not historical_msg.content.strip():
            continue

        role = "model" if historical_msg.author.bot else "user"
        
        # Format content based on role
        if role == "user":
            content = f"{historical_msg.author.display_name} (<@{historical_msg.author.id}>): {historical_msg.content}"
        else:
            content = historical_msg.content

        # Merge consecutive messages from the same role to maintain the alternating structure
        if gemini_conversation and gemini_conversation[-1]['role'] == role:
            gemini_conversation[-1]['parts'][-1]['text'] += f"\n{content}"
        else:
            gemini_conversation.append({'role': role, 'parts': [{'text': content}]})
    return gemini_conversation

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
genai_client = google_genai.Client(api_key=gemini_api_key)  # The new, central GenAI client


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
        gemini_conversation = await build_gemini_conversation(messages_history)

        async with message.channel.typing():
            try:
                logging.info(f'{message.author} sent LLM request.')

                # This part remains the same, just using the new genai_client
                # The tool configuration should also be part of the main config object.
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

                # Use the non-streaming method to get the full response at once.
                response = await chat_session.send_message(
                    # The message content is already part of the history, so we can send an empty message
                    # to just get the response to the last user message in the history.
                    message=""
                )

                # The full reply is available directly in the response object.
                reply = response.text
                reply = reply.strip()
            
                # Split the response into chunks to fit within Discord's character limit (1900 chars).
                max_length = 1900
                while reply:
                    chunk = reply[:max_length]
                    await message.channel.send(chunk)
                    reply = reply[max_length:]
            except google_genai.APIError as e:
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
        # The setup_hook will handle loading extensions and syncing commands.
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())