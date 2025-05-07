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

    #if "G3" in message.content:
        #pass
        #await message.channel.send("G3")


    if discord_client.user.mention in message.content:
        # Use your updated system message with instructions not to include the sender tag in the reply.
        system_message = {
            "role": "system",
            "content": (
                
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
        }

        # Retrieve the last X messages from the channel for context (oldest first)
        #TODO: dynamically change this depending on load / context?
        messages_history = [msg async for msg in message.channel.history(limit=100)]
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
                model="gpt-4.1",
                messages=conversation,
                max_completion_tokens=2000
            )
            reply = response.choices[0].message.content.strip()
            #await message.channel.send(reply)
        
            max_length = 1500
            while reply:
                chunk = reply[:max_length]
                await message.channel.send(chunk)
                reply = reply[max_length:]

        except Exception as e:
            await message.channel.send(f"Error with LLM: {e}")


discord_client.run(token)