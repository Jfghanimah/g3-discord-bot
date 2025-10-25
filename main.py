import os
from dotenv import load_dotenv
import logging
import discord
from google import genai as google_genai
from google.genai import types as google_types

# Load environment variables
load_dotenv()
token = os.getenv('BOT_SECRET_TOKEN')

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

async def build_gemini_conversation(message_history):
    """Builds a conversation history formatted for the Gemini API, merging consecutive roles."""
    gemini_conversation = []
    for historical_msg in message_history:
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
            gemini_conversation[-1]['parts'][-1] += f"\n{content}"
        else:
            gemini_conversation.append({'role': role, 'parts': [content]})
    return gemini_conversation

# Initialize the Discord client
intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents) # The Discord client
genai_client = google_genai.Client() # The new, central GenAI client

@discord_client.event
async def on_ready():
    logging.info(f'We have logged in as {discord_client.user}')


@discord_client.event
async def on_message(message):

    if message.author == discord_client.user:
        return

    if discord_client.user.mention in message.content:
        # Retrieve and build the conversation history
        messages_history = [msg async for msg in message.channel.history(limit=HISTORY_LIMIT)]
        messages_history.reverse()
        gemini_conversation = await build_gemini_conversation(messages_history)

        # For chat sessions, the system instruction must be the first part of the history.
        gemini_conversation.insert(0, {'role': 'system', 'parts': [{'text': SYSTEM_INSTRUCTION}]})

        # Define the tools to be used for the chat session.
        tools = [
            google_types.Tool(google_search=google_types.GoogleSearch()),
            google_types.Tool(url_context=google_types.UrlContext()),
        ]

        async with message.channel.typing():
            try:
                logging.info(f'{message.author} sent LLM request.')
                
                chat_session = await genai_client.aio.chats.create(model=MODEL_NAME, history=gemini_conversation, tools=tools)

                response_stream = await chat_session.send_message_stream(
                    message=f"{message.author.display_name} (<@{message.author.id}>): {message.content}"
                )

                reply = ""
                tool_use_notified = False
                async for chunk in response_stream:
                    # Check if the model is making a function call (i.e., using a tool)
                    if not tool_use_notified and chunk.function_calls:
                        # Notify the user that a tool is being used.
                        # We can make this more specific if we check the function name.
                        await message.channel.send("_Using tools to find the answer..._")
                        tool_use_notified = True

                    if chunk.text:
                        reply += chunk.text
                
                reply = reply.strip()
            
                # Split the response into chunks to fit within Discord's character limit.
                max_length = 1900
                while reply:
                    chunk = reply[:max_length]
                    await message.channel.send(chunk)
                    reply = reply[max_length:]
    
            except Exception as e:
                logging.exception("An error occurred while processing a message.")
                await message.channel.send(f"Error with LLM: {e}")


discord_client.run(token)