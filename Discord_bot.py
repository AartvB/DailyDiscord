import os
import discord
import schedule
from dotenv import load_dotenv
import praw
import sqlite3
import time

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
CHANNEL = os.getenv('DISCORD_CHANNEL')

reddit = praw.Reddit('bot1')
reddit.validate_on_submit = True
subreddit = reddit.subreddit("dailygames")

def doLinkCheck():
    print("New post check")
    conn = sqlite3.connect("DailyGamesPosts.db")
    cursor = conn.cursor()

    posts = reversed(list(subreddit.new(limit=20)))
    for post in posts:
        cursor.execute("SELECT COUNT(*) FROM posts WHERE id = ?", (post.id,))
        linked_to_post = cursor.fetchone()[0] > 0

        if not linked_to_post and int(post.created_utc) < int(time.time()) - 5*60:
            cursor.execute("INSERT INTO posts (id) VALUES (?)", (post.id,))
            conn.commit()

            client = discord.Client(intents=discord.Intents.default())

            @client.event
            async def on_ready():
                for guild in client.guilds:
                    if guild.name == GUILD:
                        for channel in guild.channels:
                            if channel.name == CHANNEL:
                                await channel.send('u/{author} has created a new post called "{title}". You can find it here: https://www.reddit.com/r/dailygames/comments/{id}/'.format(author=post.author.name.translate(str.maketrans({'_':  r'\_', '*':  r'\*', '~':  r'\~'})) if post.author else '[deleted]',title=post.title.translate(str.maketrans({'_':  r'\_', '*':  r'\*', '~':  r'\~'})),id=post.id))
                                await client.close() 
            client.run(TOKEN)
    conn.close()

schedule.every(1).minute.do(doLinkCheck)
while True:
    try:
        schedule.run_pending()
        time.sleep(1)
    except Exception as e:
        print(e)
        pass