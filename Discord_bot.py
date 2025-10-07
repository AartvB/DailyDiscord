import os
import discord
import asyncio
from dotenv import load_dotenv
import asyncpraw
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
CHANNEL = os.getenv('DISCORD_CHANNEL')
email_account = os.getenv('ACCOUNT')
email_app_password = os.getenv('PASSWORD')
email_receiver = os.getenv('RECEIVER')

def send_email(subject, body):
    # Create email message
    msg = MIMEMultipart()
    msg["From"] = email_account
    msg["To"] = email_receiver
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    # Connect to Gmail SMTP server and send email
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(email_account, email_app_password)
        server.sendmail(email_account, email_receiver, msg.as_string())
        server.quit()
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error sending email: {e}")

# Autocomplete helpers
async def autocomplete_subscribe(interaction: discord.Interaction, current: str):
    conn = sqlite3.connect("DailyGamesPosts.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM series WHERE name LIKE ?", (f"{current}%",))
    results = [row[0] for row in cursor.fetchall()]
    conn.close()
    return [discord.app_commands.Choice(name=name, value=name) for name in results[:25]]  # Max 25 choices

async def autocomplete_unsubscribe(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    conn = sqlite3.connect("DailyGamesPosts.db")
    cursor = conn.cursor()
    cursor.execute("SELECT seriesname FROM subscriptions WHERE userid = ? AND seriesname LIKE ? AND platform = 'discord'", (user_id, f"{current}%"))
    results = [row[0] for row in cursor.fetchall()]
    conn.close()
    return [discord.app_commands.Choice(name=name, value=name) for name in results[:25]]  # Max 25 choices

class MyClient(discord.Client):
    async def setup_hook(self):
        self.reddit = asyncpraw.Reddit('bot1')
        self.subreddit = await self.reddit.subreddit("dailygames")
        self.bg_task = self.loop.create_task(background_task(self))
        self.txt_task = self.loop.create_task(process_txt_files(self))
        self.perform_bot_action_task = self.loop.create_task(perform_bot_action_from_distance(self))
        self.tree = discord.app_commands.CommandTree(self)

        @self.tree.command(name="subscribe", description="Subscribe to a DailyGame")
        @discord.app_commands.describe(text="The series to subscribe to")
        @discord.app_commands.autocomplete(text=autocomplete_subscribe)
        async def subscribe(interaction: discord.Interaction, text: str):
            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM series")
            series_names = [row[0] for row in cursor.fetchall()]
            if text not in series_names:
                await interaction.response.send_message(f"Series '{text}' not found. Available series: {', '.join(series_names)}", ephemeral=True)
                conn.close()
                return            
            cursor.execute("INSERT OR IGNORE INTO subscriptions (userid, seriesname, platform) VALUES (?, ?, 'discord')", (interaction.user.id, text))
            conn.commit()
            conn.close()
            await interaction.response.send_message(f"You have subscribed to '{text}'.", ephemeral=True)

        @self.tree.command(name="unsubscribe", description="Unsubscribe from a DailyGame")
        @discord.app_commands.describe(text="The series to unsubscribe from")
        @discord.app_commands.autocomplete(text=autocomplete_unsubscribe)
        async def unsubscribe(interaction: discord.Interaction, text: str):
            user_id = interaction.user.id
            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM subscriptions WHERE userid = ? AND seriesname = ? AND platform = 'discord'", (user_id, text))
            is_subscribed = cursor.fetchone()
            if not is_subscribed:
                await interaction.response.send_message(f"You are not subscribed to '{text}'.", ephemeral=True)
                conn.close()
            else:
                cursor.execute("DELETE FROM subscriptions WHERE userid = ? AND seriesname = ? AND platform = 'discord'", (user_id, text))
                conn.commit()
                conn.close()
                await interaction.response.send_message(f"You have unsubscribed from '{text}'.", ephemeral=True)

        @self.tree.command(name="subscriptions", description="Show all DailyGames you are subscribed to")
        async def viewSubscriptions(interaction: discord.Interaction):
            user_id = interaction.user.id
            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT seriesname FROM subscriptions WHERE userid = ? AND platform = 'discord'", (user_id,))
            subscriptions = [row[0] for row in cursor.fetchall()]
            conn.close()
            if subscriptions:
                await interaction.response.send_message(f"You are subscribed to: {', '.join(subscriptions)}", ephemeral=True)
            else:
                await interaction.response.send_message("You are not subscribed to any series.", ephemeral=True)

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
            message = 'u/{author} has created a new post called "{title}". You can find it here: https://www.reddit.com/r/dailygames/comments/{id}/'.format(author=post.author.name.translate(str.maketrans({'_':  r'\_', '*':  r'\*', '~':  r'\~'})) if post.author else '[deleted]',title=post.title.translate(str.maketrans({'_':  r'\_', '*':  r'\*', '~':  r'\~'})),id=post.id)

            # Detect series
            cursor.execute("SELECT name FROM series")
            series_names = [row[0] for row in cursor.fetchall()]
            matched_series = [series_name for series_name in series_names if series_name.lower() in post.title.lower()]
            if (len(matched_series) == 0 or len(matched_series) > 1):
                cursor.execute("INSERT INTO posts (id) VALUES (?)", (post.id,))
                send_email("Series of post not recognized!",f"The series of post {post.id} with title {post.title} can be any one of the following: {matched_series}")
            else:
                cursor.execute("INSERT INTO posts (id, seriesname) VALUES (?, ?)", (post.id,matched_series[0]))
                cursor.execute("SELECT userid FROM subscriptions WHERE seriesname = ? AND platform = 'discord'", (matched_series[0],))
                user_ids = [int(row[0]) for row in cursor.fetchall()]
                tags = []
                for guild in client.guilds:
                    if guild.name == GUILD:
                        for member in guild.members:
                            if member.id in user_ids:
                                tags.append(member.mention)
                if tags:
                    message += f"\nI think it is part of the series named {matched_series[0]}.\nMembers subscribed to this DailyGame: " + " ".join(tags)
            conn.commit()
            for guild in client.guilds:
                if guild.name == GUILD:
                    for channel in guild.channels:
                        if channel.name == CHANNEL:
                            await channel.send(message)
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

async def perform_bot_action_from_distance(client):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            filename = 'bot_action.txt'
            if os.path.isfile(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read()
                print(f"About to perform bot action:\n{content}")
                if content.startswith('addSeries(') and content.endswith(')'):
                    series_name = content[len('addSeries("'):-2]
                    conn = sqlite3.connect("DailyGamesPosts.db")
                    cursor = conn.cursor()
                    cursor.execute("INSERT OR IGNORE INTO series (name) VALUES (?)", (series_name,))
                    conn.commit()
                    conn.close()
                    print(f"Series '{series_name}' added to database.")
                elif content.startswith('addPostToSeries(') and content.endswith(')'):
                    args = content[len('addPostToSeries("'):-2]
                    postid, series_name = args.split('","')
                    conn = sqlite3.connect("DailyGamesPosts.db")
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1 FROM posts WHERE id = ?", (postid,))
                    post_exists = cursor.fetchone()
                    cursor.execute("SELECT 1 FROM series WHERE name = ?", (series_name,))
                    series_exists = cursor.fetchone()
                    if post_exists and series_exists:
                        cursor.execute("UPDATE posts SET seriesname = ? WHERE id = ?",(series_name, postid))
                        conn.commit()
                        print(f"Post '{postid}' assigned to series '{series_name}'.")

                        cursor.execute("SELECT userid FROM subscriptions WHERE seriesname = ? AND platform = 'discord'", (series_name,))
                        user_ids = [int(row[0]) for row in cursor.fetchall()]
                        if (len(user_ids) > 0):
                            for guild in client.guilds:
                                if guild.name == GUILD:
                                    for channel in guild.channels:
                                        if channel.name == CHANNEL:
                                            # Find the original bot message about this post
                                            async for msg in channel.history(limit=50):
                                                if postid in msg.content and msg.author == client.user:
                                                    # Get users subscribed to this series
                                                    tags = []
                                                    for member in guild.members:
                                                        if member.id in user_ids:
                                                            tags.append(member.mention)
                                                    reply = f"I first did not (correctly) recognize the series of this post, but I do recognize it now.\nIt is part of the series named {series_name}.\nUsers subscribed to this series: {' '.join(tags) if tags else 'None'}"
                                                    await msg.reply(reply)
                                                    break

                    else:
                        print("Post or Series not recognized!")
                    conn.commit()
                    conn.close()
                else:
                    print("Action not recognized")
                os.remove(filename)
        except Exception as e:
            print(f"Error processing bot_domain_message file: {e}")
        await asyncio.sleep(10)

intents = discord.Intents.default()
intents.members = True
client = MyClient(intents=intents)

@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('Guilds the bot is in:')
    for guild in client.guilds:
        print(f"- {guild.name} (ID: {guild.id})")
    
    await client.tree.sync()
    print("Slash commands synced globally.")
    commands = await client.tree.fetch_commands()

    print("Registered slash commands:")
    for cmd in commands:
        print(f"- /{cmd.name}: {cmd.description}")
    print("These were are of the registered slash commands.")

client.run(TOKEN)