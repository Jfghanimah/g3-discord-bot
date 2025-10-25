import os
from dotenv import load_dotenv
import logging
import discord
from google import genai as google_genai
from google.genai import types as google_types

# Load environment variables
load_dotenv()
token = os.getenv('BOT_SECRET_TOKEN')
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

async def build_gemini_conversation(
    message_history: list[discord.Message]
) -> list[dict]:
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

# Initialize the Discord client
intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)  # The Discord client
genai_client = google_genai.Client(api_key=gemini_api_key)  # The new, central GenAI client

@discord_client.event
async def on_ready():
    logging.info(f'We have logged in as {discord_client.user}')


@discord_client.event
async def on_message(message: discord.Message):
    """
    Handles incoming Discord messages, processing them with the Gemini LLM if the bot is mentioned.
    """

    if message.author == discord_client.user:
        return

    if discord_client.user.mention in message.content:
        # Retrieve and build the conversation history
        messages_history = [msg async for msg in message.channel.history(limit=HISTORY_LIMIT)]
        messages_history.reverse()
        gemini_conversation = await build_gemini_conversation(messages_history)

        async with message.channel.typing():
            try:
                logging.info(f'{message.author} sent LLM request.')

                # Pass the system instruction directly as a dictionary in the config.
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

                response_stream = await chat_session.send_message_stream(
                    # The message content is already part of the history, so we can send an empty message
                    # to just get the response to the last user message in the history.
                    message=""
                )

                reply = ""
                tool_use_notified = False
                async for chunk in response_stream:
                    # Check if the model is making a function call (i.e., using a tool) and notify the user
                    if not tool_use_notified and chunk.function_calls:
                        tool_names = [fc.name for fc in chunk.function_calls]
                        if tool_names:
                            await message.channel.send(f"_Using tools ({', '.join(tool_names)}) to find the answer..._")
                        else:
                            # Fallback if for some reason function_calls is not empty but names are missing
                            await message.channel.send("_Using tools to find the answer..._")
                        tool_use_notified = True

                    if chunk.text:
                        reply += chunk.text
                
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


discord_client.run(token)