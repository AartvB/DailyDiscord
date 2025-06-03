import os
import discord
import asyncio
from dotenv import load_dotenv
import asyncpraw
import sqlite3
import time

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
CHANNEL = os.getenv('DISCORD_CHANNEL')

class MyClient(discord.Client):
    async def setup_hook(self):
        self.reddit = asyncpraw.Reddit('bot1')
        self.subreddit = await self.reddit.subreddit("dailygames")
        self.bg_task = self.loop.create_task(background_task(self))
        self.txt_task = self.loop.create_task(process_txt_files(self))

async def doLinkCheck(client):
    print("New post check")
    conn = sqlite3.connect("DailyGamesPosts.db")
    cursor = conn.cursor()
    posts = []
    async for post in client.subreddit.new(limit=20):
        posts.append(post)
    for post in reversed(posts):
        cursor.execute("SELECT COUNT(*) FROM posts WHERE id = ?", (post.id,))
        linked_to_post = cursor.fetchone()[0] > 0
        if not linked_to_post and int(post.created_utc) < int(time.time()) - 5*60:
            cursor.execute("INSERT INTO posts (id) VALUES (?)", (post.id,))
            conn.commit()
            for guild in client.guilds:
                if guild.name == GUILD:
                    for channel in guild.channels:
                        if channel.name == CHANNEL:
                            await channel.send('u/{author} has created a new post called "{title}". You can find it here: https://www.reddit.com/r/dailygames/comments/{id}/'.format(author=post.author.name.translate(str.maketrans({'_':  r'\_', '*':  r'\*', '~':  r'\~'})) if post.author else '[deleted]',title=post.title.translate(str.maketrans({'_':  r'\_', '*':  r'\*', '~':  r'\~'})),id=post.id))
    conn.close()

async def background_task(client):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            await doLinkCheck(client)
        except Exception as e:
            print(e)
        await asyncio.sleep(60)

async def process_txt_files(client):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            filename = 'bot_domain_message.txt'
            if os.path.isfile(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read()
                print(f"About to send message to #bot-domain:\n{content}")
                for guild in client.guilds:
                    for channel in guild.channels:
                        if channel.name == 'bot-domain':
                            # Discord messages have a 2000 character limit
                            for chunk in [content[i:i+2000] for i in range(0, len(content), 2000)]:
                                await channel.send(chunk)
                os.remove(filename)
        except Exception as e:
            print(f"Error processing bot_domain_message file: {e}")
        await asyncio.sleep(10)

intents = discord.Intents.default()
client = MyClient(intents=intents)

@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('------')

client.run(TOKEN)