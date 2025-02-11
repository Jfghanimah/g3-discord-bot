import os
from openai import OpenAI
from dotenv import load_dotenv
import discord
from random import random

# Load environment variables
load_dotenv()
openai_client = OpenAI(api_key=os.getenv('OPENAI_KEY'))
token = os.getenv('BOT_SECRET_TOKEN')

# Initialize the Discord client
intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)

g3_streak = 0  # Initializing the streak counter

@discord_client.event
async def on_ready():
    print(f'We have logged in as {discord_client.user}')


@discord_client.event
async def on_message(message):
    global g3_streak

    if message.author == discord_client.user:
        return


    if discord_client.user.mention in message.content:
        # Use your updated system message with instructions not to include the sender tag in the reply.
        system_message = {
            "role": "system",
            "content": (
                "You are G3 Bot, an intelligent and casual AI assistant designed for a lively Discord group chat. "
                "This chat involves multiple participants, each with their own unique voice, and the conversation is informal, playful, and sometimes chaotic. "
                "Every message in this conversation is prefixed with the sender's display name and Discord ID in the format 'NAME (<@ID_NUMBER>): MESSAGE'. "
                "It is important that you recognize this as a multi-user group chat; you must pay close attention to the entire conversation context to understand instructions and maintain coherence. "
                "When you generate a response, do not include your own sender tag (for example, 'G3 Bot:' or 'Chat:') at the beginning—simply reply with the answer text. "
                "When you need to discord mention another user, you can use the Discord mention format <@ID_NUMBER> so that it converts to a real mention on Discord. "
                "use this sparingly to avoid spam but when explicity told to do it feel free to do it, but when just talking about someone there is no need."
                "Sometimes the user may refer to you as @G3 Bot, G3 Bot, @Chat or Chat."
                "For reference your Discord ID is <@1145214013555363891>"
            )
        }

        # Retrieve the last 40 messages from the channel for context (oldest first)
        messages_history = [msg async for msg in message.channel.history(limit=40)]
        messages_history.reverse()

        # Build the conversation context by including the last 10 messages with sender names and Discord IDs.
        conversation = [system_message]
        for historical_msg in messages_history:
            if not historical_msg.content.strip():
                continue
            if historical_msg.author.bot:
                conversation.append({
                    "role": "assistant",
                    "content": historical_msg.content
                })
            else:
                conversation.append({
                    "role": "user",
                    "content": f"{historical_msg.author.display_name} (<@{historical_msg.author.id}>): {historical_msg.content}"
                })

        try:
            print(f'{message.author} sent LLM request.')
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=conversation,
                max_completion_tokens=2048
            )
            reply = response.choices[0].message.content.strip()
            await message.channel.send(reply)
        except Exception as e:
            await message.channel.send(f"Error with LLM: {e}")


discord_client.run(token)
