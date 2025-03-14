import os
import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
CHANNEL = os.getenv('DISCORD_CHANNEL')

client = discord.Client(intents=discord.Intents.default())

@client.event
async def on_ready():
    for guild in client.guilds:
        if guild.name == GUILD:
            for channel in guild.channels:
                if channel.name == CHANNEL:
                    await channel.send('test')
                    await client.close() 

client.run(TOKEN)