# This example requires the 'message_content' intent.

import discord

from dotenv import load_dotenv
import os

load_dotenv()
token = os.getenv('BOT_SECRET_TOKEN')


intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith('G3'):
        await message.channel.send('G3')

client.run(token)
