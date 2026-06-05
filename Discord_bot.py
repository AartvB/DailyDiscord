from email.mime import text
import os
import discord
import asyncio
from dotenv import load_dotenv
import asyncpraw
import sqlite3
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re

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
    user_id = interaction.user.id
    conn = sqlite3.connect("DailyGamesPosts.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM series WHERE LOWER(name) LIKE ?", (f"{current.lower()}%",))
    results = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT seriesname FROM subscriptions WHERE userid = ? AND LOWER(seriesname) LIKE ? AND platform = 'discord'", (user_id, f"{current.lower()}%"))
    subscriptions = [row[0] for row in cursor.fetchall()]
    results = [name for name in results if name not in subscriptions]
    results.sort(key=str.casefold)
    conn.close()
    return [discord.app_commands.Choice(name=name, value=name) for name in results[:25]]  # Max 25 choices

async def autocomplete_unsubscribe(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    conn = sqlite3.connect("DailyGamesPosts.db")
    cursor = conn.cursor()
    cursor.execute("SELECT seriesname FROM subscriptions WHERE userid = ? AND LOWER(seriesname) LIKE ? AND platform = 'discord'", (user_id, f"{current.lower()}%"))
    results = [row[0] for row in cursor.fetchall()]
    results.sort(key=str.casefold)
    conn.close()
    return [discord.app_commands.Choice(name=name, value=name) for name in results[:25]]  # Max 25 choices

async def autocomplete_all_series(interaction: discord.Interaction, current: str):
    conn = sqlite3.connect("DailyGamesPosts.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM series WHERE LOWER(name) LIKE ?", (f"{current.lower()}%",))
    results = [row[0] for row in cursor.fetchall()]
    results.sort(key=str.casefold)
    conn.close()
    return [discord.app_commands.Choice(name=name, value=name) for name in results[:25]]  # Max 25 choices

class MyClient(discord.Client):
    async def setup_hook(self):
        self.reddit = asyncpraw.Reddit('bot1')
        self.subreddit = await self.reddit.subreddit("dailygames")
        self.bg_task = self.loop.create_task(background_task(self))
        self.txt_task = self.loop.create_task(process_txt_files(self))
#        self.perform_bot_action_task = self.loop.create_task(perform_bot_action_from_distance(self))
        self.tree = discord.app_commands.CommandTree(self)

        @self.tree.command(name="subscribe", description="Subscribe to a DailyGame")
        @discord.app_commands.describe(text="The series to subscribe to")
        @discord.app_commands.autocomplete(text=autocomplete_subscribe)
        async def subscribe(interaction: discord.Interaction, text: str):
            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM series")
            series_rows = [row[0] for row in cursor.fetchall()]
            series_map = {name.lower(): name for name in series_rows}
            if text.lower() not in series_map:
                await interaction.response.send_message(f"Series '{text}' not found. Available series: {', '.join(series_rows)}", ephemeral=True)
                conn.close()
                return
            actual_name = series_map[text.lower()]
            cursor.execute("INSERT OR IGNORE INTO subscriptions (userid, seriesname, platform) VALUES (?, ?, 'discord')", (interaction.user.id, actual_name))
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
            cursor.execute("SELECT seriesname FROM subscriptions WHERE userid = ? AND platform = 'discord'", (user_id,))
            subs = [row[0] for row in cursor.fetchall()]
            matching = next((s for s in subs if s.lower() == text.lower()), None)
            if not matching:
                await interaction.response.send_message(f"You are not subscribed to '{text}'.", ephemeral=True)
                conn.close()
            else:
                cursor.execute("DELETE FROM subscriptions WHERE userid = ? AND LOWER(seriesname) = LOWER(?) AND platform = 'discord'", (user_id, text))
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

        @self.tree.command(name="addseries", description="Add a new DailyGame to subscribe to")
        @discord.app_commands.describe(text="The name of the new series")
        @discord.app_commands.checks.has_role('Human Overlord')
        async def addSeries(interaction: discord.Interaction, text: str):
            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM series WHERE LOWER(name) = LOWER(?)", (text,))
            existing = cursor.fetchone()
            if existing:
                await interaction.response.send_message(f"Series '{text}' already exists as '{existing[0]}'.", ephemeral=True)
            else:
                cursor.execute("INSERT INTO series (name) VALUES (?)", (text,))
                conn.commit()
                await interaction.response.send_message(f"Users can now subscribe to series '{text}'.", ephemeral=True)
                for guild in client.guilds:
                    if guild.name == GUILD:
                        for channel in guild.channels:
                            if channel.name == CHANNEL:
                                await channel.send(f"It is now possible to subscribe to the series named {text}!")
            send_email("New series added!",f"The series '{text}' has been added to the database by {interaction.user.name}.")
            conn.close()

        @self.tree.command(name="renameseries", description="Rename a DailyGame")
        @discord.app_commands.describe(old_name="The current name of the series", new_name="The new name for the series")
        @discord.app_commands.autocomplete(old_name=autocomplete_all_series)
        @discord.app_commands.checks.has_role('Human Overlord')
        async def renameSeries(interaction: discord.Interaction, old_name: str, new_name: str):
            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM series WHERE LOWER(name) = LOWER(?)", (old_name,))
            old_row = cursor.fetchone()
            old_exists = old_row is not None
            if old_row:
                old_name = old_row[0]
            if not old_exists:
                await interaction.response.send_message(f"Series '{old_name}' not found.", ephemeral=True)
            else:
                cursor.execute("SELECT name FROM series WHERE LOWER(name) = LOWER(?)", (new_name,))
                new_row = cursor.fetchone()
                new_exists = new_row is not None
                if new_exists and (new_row[0].lower() != old_name.lower()):
                    await interaction.response.send_message(f"Series '{new_name}' already exists.", ephemeral=True)
                else:
                    cursor.execute("UPDATE series SET name = ? WHERE LOWER(name) = LOWER(?)", (new_name, old_name))
                    cursor.execute("UPDATE subscriptions SET seriesname = ? WHERE LOWER(seriesname) = LOWER(?)", (new_name, old_name))
                    cursor.execute("UPDATE posts SET seriesname = ? WHERE LOWER(seriesname) = LOWER(?)", (new_name, old_name))
                    conn.commit()
                    await interaction.response.send_message(f"You renamed Series '{old_name}' to '{new_name}'.", ephemeral=True)
                    for guild in client.guilds:
                        if guild.name == GUILD:
                            for channel in guild.channels:
                                if channel.name == CHANNEL:
                                    await channel.send(f"The series '{old_name}' has been renamed to '{new_name}'.")
            send_email("Series renamed!",f"The series '{old_name}' has been renamed to '{new_name}' by {interaction.user.name}.")
            conn.close()

        @self.tree.command(name="addposttoseries", description="Add a post to a series if it was not correctly recognized")
        @discord.app_commands.describe(series_name="The name of the series to add the post to")
        @discord.app_commands.autocomplete(series_name=autocomplete_all_series)
        @discord.app_commands.checks.has_role('Human Overlord')
        async def addposttoseries(interaction: discord.Interaction, series_name: str, reddit_link: str):
            match = re.search(r'comments/([a-z0-9]+)/', reddit_link)
            if not match:
                await interaction.response.send_message("Invalid Reddit link format. Please provide a link to a DailyGames post.", ephemeral=True)
                return
            postid = match.group(1)

            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM posts WHERE id = ?", (postid,))
            post_exists = cursor.fetchone()
            cursor.execute("SELECT name FROM series WHERE LOWER(name) = LOWER(?)", (series_name,))
            series_row = cursor.fetchone()
            series_exists = series_row is not None
            if series_row:
                series_name = series_row[0]
            if post_exists and series_exists:
                cursor.execute("UPDATE posts SET seriesname = ? WHERE id = ?",(series_name, postid))
                conn.commit()
                await interaction.response.send_message(f"Post '{postid}' assigned to series '{series_name}'.", ephemeral=True)

                cursor.execute("SELECT userid FROM subscriptions WHERE LOWER(seriesname) = LOWER(?) AND platform = 'discord'", (series_name,))
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
                                            reply = f"I first did not (correctly) recognize the series of this post, but I do recognize it now.\nIt is part of the series named {series_name}."
                                            if len(tags) > 0:
                                                reply += f"\nCircadians subscribed to this series: " + " ".join(tags)
                                            await msg.reply(reply)
                                            break
            else:
                if not post_exists:
                    await interaction.response.send_message(f"Post with ID '{postid}' not found in the database.", ephemeral=True)
                if not series_exists:
                    await interaction.response.send_message(f"Series '{series_name}' not found.", ephemeral=True)
            conn.commit()
            conn.close()


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
                message += f"\nI think it is part of the series named {matched_series[0]}."
                cursor.execute("INSERT INTO posts (id, seriesname) VALUES (?, ?)", (post.id,matched_series[0]))
                cursor.execute("SELECT userid FROM subscriptions WHERE LOWER(seriesname) = LOWER(?) AND platform = 'discord'", (matched_series[0],))
                user_ids = [int(row[0]) for row in cursor.fetchall()]
                tags = []
                for guild in client.guilds:
                    if guild.name == GUILD:
                        for member in guild.members:
                            if member.id in user_ids:
                                tags.append(member.mention)
                if len(tags) > 0:
                    message += f"\nCircadians subscribed to this DailyGame: " + " ".join(tags)
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

intents = discord.Intents.default()
intents.members = True
client = MyClient(intents=intents)

@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('Guilds the bot is in:')
    for guild in client.guilds:
        print(f"- {guild.name} (ID: {guild.id})")
    
#    guild = discord.Object(id=1292147569908125816) # DailyGames server
#    client.tree.copy_global_to(guild=guild)
#    await client.tree.sync(guild=guild)
#    print("Slash commands synced locally.")

    await client.tree.sync()
    print("Slash commands synced globally.")

    print("Registered slash commands:")
    commands = await client.tree.fetch_commands()
    for cmd in commands:
        print(f"- /{cmd.name}: {cmd.description}")
    print("These were all of the registered slash commands.")

client.run(TOKEN)