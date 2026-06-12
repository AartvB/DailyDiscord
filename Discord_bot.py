import os
from xmlrpc import client
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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from icalendar import Calendar

AMSTERDAM_TZ = ZoneInfo("Europe/Amsterdam")
UTC_TZ = ZoneInfo("UTC")

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
NEW_POST_CHANNEL = os.getenv('NEW_POST_CHANNEL')
DAILY_RUGBY_CHANNEL_ID = os.getenv('DAILY_RUGBY_CHANNEL_ID')
DAILY_DATE_CHANNEL_ID = os.getenv('DAILY_DATE_CHANNEL_ID')
TEST_CHANNEL_ID = os.getenv('TEST_CHANNEL_ID')
ICAL_URL = os.getenv('ICAL_URL')
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
async def autocomplete_subscribe_rugby_matches(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    while True:
        try:
            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT matchname FROM rugbymatches WHERE LOWER(matchname) LIKE ?", (f"{current.lower()}%",))
            results = [row[0] for row in cursor.fetchall()]
            cursor.execute("SELECT matchname FROM rugbymatchsubscriptions WHERE userid = ? AND LOWER(matchname) LIKE ?", (user_id, f"{current.lower()}%"))
            subscriptions = [row[0] for row in cursor.fetchall()]
            results = [name for name in results if name not in subscriptions]
            results.sort(key=str.casefold)
            conn.close()
            return [discord.app_commands.Choice(name=name, value=name) for name in results]
        except Exception as e:
            print(f"Error in autocomplete_subscribe_rugby_matches: {e}")
        await asyncio.sleep(2)

async def autocomplete_unsubscribe_rugby_matches(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    while True:
        try:
            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT matchname FROM rugbymatchsubscriptions WHERE userid = ? AND LOWER(matchname) LIKE ?", (user_id, f"{current.lower()}%"))
            results = [row[0] for row in cursor.fetchall()]
            results.sort(key=str.casefold)
            conn.close()
            return [discord.app_commands.Choice(name=name, value=name) for name in results]
        except Exception as e:
            print(f"Error in autocomplete_unsubscribe_rugby_matches: {e}")
        await asyncio.sleep(2)

async def autocomplete_subscribe(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    while True:
        try:
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
        except Exception as e:
            print(f"Error in autocomplete_subscribe: {e}")
        await asyncio.sleep(2)
    

async def autocomplete_unsubscribe(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    while True:
        try:
            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT seriesname FROM subscriptions WHERE userid = ? AND LOWER(seriesname) LIKE ? AND platform = 'discord'", (user_id, f"{current.lower()}%"))
            results = [row[0] for row in cursor.fetchall()]
            results.sort(key=str.casefold)
            conn.close()
            return [discord.app_commands.Choice(name=name, value=name) for name in results[:25]]  # Max 25 choices
        except Exception as e:
            print(f"Error in autocomplete_unsubscribe: {e}")
        await asyncio.sleep(2)
    return [discord.app_commands.Choice(name=name, value=name) for name in results[:25]]  # Max 25 choices

async def autocomplete_all_series(interaction: discord.Interaction, current: str):
    while True:
        try:
            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM series WHERE LOWER(name) LIKE ?", (f"{current.lower()}%",))
            results = [row[0] for row in cursor.fetchall()]
            results.sort(key=str.casefold)
            conn.close()
            return [discord.app_commands.Choice(name=name, value=name) for name in results[:25]]  # Max 25 choices
        except Exception as e:
            print(f"Error in autocomplete_all_series: {e}")
        await asyncio.sleep(2)

async def autocomplete_rugby_team(interaction: discord.Interaction, current: str):
    
    while True:
        try:
            conn = sqlite3.connect("rugby.db")
            cursor = conn.cursor()
            cursor.execute("SELECT country, username FROM teams WHERE LOWER(country) LIKE ?", (f"{current.lower()}%",))
            results = cursor.fetchall()
            cursor.execute("SELECT teamA FROM planned_matches")
            teamA_results = [row[0] for row in cursor.fetchall()]
            cursor.execute("SELECT teamB FROM planned_matches")
            teamB_results = [row[0] for row in cursor.fetchall()]
            results = list(set([result[0] for result in results if result[1] in teamA_results or result[1] in teamB_results]))
            results.sort(key=str.casefold)
            conn.close()
            return [discord.app_commands.Choice(name=name, value=name) for name in results]
        except Exception as e:
            print(f"Error in autocomplete_rugby_team: {e}")
        await asyncio.sleep(2)

class MyClient(discord.Client):
    async def setup_hook(self):
        self.reddit = asyncpraw.Reddit('bot1')
        self.subreddit = await self.reddit.subreddit("dailygames")
        self.bg_task = self.loop.create_task(background_task(self))
        self.txt_task = self.loop.create_task(process_txt_files(self))
        self.rugby_task = self.loop.create_task(activate_rugby_report(self))
        self.rugby_message_task = self.loop.create_task(send_rugby_message(self))
        self.date_task = self.loop.create_task(send_daily_date_message(self))
#        self.perform_bot_action_task = self.loop.create_task(perform_bot_action_from_distance(self))
        self.tree = discord.app_commands.CommandTree(self)

        @self.tree.command(name="subscribe", description="Subscribe to a DailyGame")
        @discord.app_commands.describe(text="The series to subscribe to")
        @discord.app_commands.autocomplete(text=autocomplete_subscribe)
        async def subscribe(interaction: discord.Interaction, text: str):
            while True:
                try:
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
                    break
                except Exception as e:
                    print(f"Error in subscribe: {e}")
                await asyncio.sleep(2)

        @self.tree.command(name="unsubscribe", description="Unsubscribe from a DailyGame")
        @discord.app_commands.describe(text="The series to unsubscribe from")
        @discord.app_commands.autocomplete(text=autocomplete_unsubscribe)
        async def unsubscribe(interaction: discord.Interaction, text: str):
            user_id = interaction.user.id
            while True:
                try:
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
                    break
                except Exception as e:
                    print(f"Error in unsubscribe: {e}")
                await asyncio.sleep(2)

        @self.tree.command(name="subscriptions", description="Show all DailyGames you are subscribed to")
        async def viewSubscriptions(interaction: discord.Interaction):
            user_id = interaction.user.id
            while True:
                try:
                    conn = sqlite3.connect("DailyGamesPosts.db")
                    cursor = conn.cursor()
                    cursor.execute("SELECT seriesname FROM subscriptions WHERE userid = ? AND platform = 'discord'", (user_id,))
                    subscriptions = [row[0] for row in cursor.fetchall()]
                    conn.close()
                    if subscriptions:
                        await interaction.response.send_message(f"You are subscribed to: {', '.join(subscriptions)}", ephemeral=True)
                    else:
                        await interaction.response.send_message("You are not subscribed to any series.", ephemeral=True)
                    break
                except Exception as e:
                    print(f"Error in viewSubscriptions: {e}")
                await asyncio.sleep(2)

        @self.tree.command(name="rugbysubscribe", description="Subscribe to a rugby match")
        @discord.app_commands.describe(text="The match to subscribe to")
        @discord.app_commands.autocomplete(text=autocomplete_subscribe_rugby_matches)
        async def subscribe(interaction: discord.Interaction, text: str):
            while True:
                try:
                    conn = sqlite3.connect("DailyGamesPosts.db")
                    cursor = conn.cursor()
                    cursor.execute("SELECT matchname FROM rugbymatches")
                    match_rows = [row[0] for row in cursor.fetchall()]
                    match_map = {name.lower(): name for name in match_rows}
                    if text.lower() not in match_map:
                        await interaction.response.send_message(f"Match '{text}' not found. Available matches: {', '.join(match_rows)}", ephemeral=True)
                        conn.close()
                        return
                    actual_name = match_map[text.lower()]
                    cursor.execute("INSERT OR IGNORE INTO rugbymatchsubscriptions (userid, matchname) VALUES (?, ?)", (interaction.user.id, actual_name))
                    conn.commit()
                    conn.close()
                    await interaction.response.send_message(f"You have subscribed to '{text}'.", ephemeral=True)
                    break
                except Exception as e:
                    print(f"Error in subscribe: {e}")
                await asyncio.sleep(2)

        @self.tree.command(name="rugbyunsubscribe", description="Unsubscribe from a rugby match")
        @discord.app_commands.describe(text="The match to unsubscribe from")
        @discord.app_commands.autocomplete(text=autocomplete_unsubscribe_rugby_matches)
        async def unsubscribe(interaction: discord.Interaction, text: str):
            while True:
                try:
                    user_id = interaction.user.id
                    conn = sqlite3.connect("DailyGamesPosts.db")
                    cursor = conn.cursor()
                    cursor.execute("SELECT matchname FROM rugbymatchsubscriptions WHERE userid = ?", (user_id,))
                    subs = [row[0] for row in cursor.fetchall()]                    
                    matching = next((s for s in subs if s.lower() == text.lower()), None)
                    if not matching:
                        await interaction.response.send_message(f"You are not subscribed to '{text}'.", ephemeral=True)
                        conn.close()
                    else:
                        cursor.execute("DELETE FROM rugbymatchsubscriptions WHERE userid = ? AND LOWER(matchname) = LOWER(?)", (user_id, text))
                        conn.commit()
                        conn.close()
                        await interaction.response.send_message(f"You have unsubscribed from '{text}'.", ephemeral=True)
                    break
                except Exception as e:
                    print(f"Error in unsubscribe: {e}")
                await asyncio.sleep(2)

        @self.tree.command(name="getrugbyodds", description="Get the odds for a rugby team to score within a certain range")
        @discord.app_commands.describe(team="The team to get odds for")
        @discord.app_commands.describe(min_points="The minimum points to consider")
        @discord.app_commands.describe(max_points="The maximum points to consider")
        @discord.app_commands.autocomplete(team=autocomplete_rugby_team)
        async def getrugbyodds(interaction: discord.Interaction, team: str, min_points: int, max_points: int):
            from rugby_class import RugbyOddsCalculator
            roc = RugbyOddsCalculator()
            try:
                result = roc.get_score_odds(team, min_points, max_points)
                await interaction.response.send_message(f"The odds for {team} to score at least {min_points} and no more than {max_points} points against {result[0]} are: {result[1]}", ephemeral=True)
            except Exception as e:
                print(f"Error in getrugbyodds: {e}")
                await interaction.response.send_message(f"An error occurred while fetching the odds: {e}.", ephemeral=True)

        @self.tree.command(name="addseries", description="Add a new DailyGame to subscribe to")
        @discord.app_commands.describe(text="The name of the new series")
        @discord.app_commands.checks.has_role('Human Overlord')
        async def addSeries(interaction: discord.Interaction, text: str):
            while True:
                try:
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
                                    if channel.name == NEW_POST_CHANNEL:
                                        await channel.send(f"It is now possible to subscribe to the series named {text}!")
                    send_email("New series added!",f"The series '{text}' has been added to the database by {interaction.user.name}.")
                    conn.close()
                    break
                except Exception as e:
                    print(f"Error in addSeries: {e}")
                await asyncio.sleep(2)

        @self.tree.command(name="renameseries", description="Rename a DailyGame")
        @discord.app_commands.describe(old_name="The current name of the series", new_name="The new name for the series")
        @discord.app_commands.autocomplete(old_name=autocomplete_all_series)
        @discord.app_commands.checks.has_role('Human Overlord')
        async def renameSeries(interaction: discord.Interaction, old_name: str, new_name: str):
            while True:
                try:
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
                                        if channel.name == NEW_POST_CHANNEL:
                                            await channel.send(f"The series '{old_name}' has been renamed to '{new_name}'.")
                    send_email("Series renamed!",f"The series '{old_name}' has been renamed to '{new_name}' by {interaction.user.name}.")
                    conn.close()
                    break
                except Exception as e:
                    print(f"Error in renameSeries: {e}")
                await asyncio.sleep(2)

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

            while True:
                try:
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
                                        if channel.name == NEW_POST_CHANNEL:
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
                    break
                except Exception as e:
                    print(f"Error in addposttoseries: {e}")
                await asyncio.sleep(2)

        @self.tree.command(name="removebotmessage", description="Remove a message of the bot")
        @discord.app_commands.describe(message_link="The link to the message to remove")
        @discord.app_commands.checks.has_role('Botbouwer')
        async def removebotmessage(interaction: discord.Interaction, message_link: str):
            match = re.search(r'/channels/\d+/(\d+)/(\d+)', message_link)
            if not match:
                await interaction.response.send_message("Invalid message link format. Please provide a link to a Discord message.", ephemeral=True)
                return
            channel_id = int(match.group(1))
            message_id = int(match.group(2))

            channel = await client.fetch_channel(channel_id)
            if not channel:
                await interaction.response.send_message("Channel not found.", ephemeral=True)
                return

            try:
                message = await channel.fetch_message(message_id)
                if message.author != client.user:
                    await interaction.response.send_message("I can only delete my own messages.", ephemeral=True)
                    return
                await message.delete()
                await interaction.response.send_message("Message deleted successfully.", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Error deleting message: {e}", ephemeral=True)

async def doLinkCheck(client):
    print("New post check")
    while True:
        try:
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
                                if channel.name == NEW_POST_CHANNEL:
                                    await channel.send(message)
            conn.close()
            break
        except Exception as e:
            print(f"Error in doLinkCheck: {e}")
        await asyncio.sleep(2)

async def background_task(client):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            await doLinkCheck(client)
        except Exception as e:
            print(f"Error in background_task: {e}")
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

async def activate_rugby_report(client):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            filename = 'rugby_report.txt'
            if os.path.isfile(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    TEXT = f.read()
            
                print("Processing rugby report")
                conn = sqlite3.connect("DailyGamesPosts.db")
                cur = conn.cursor()

                print("Clearing all existing rugby messages from the queue.")
                cur.execute('''CREATE TABLE IF NOT EXISTS rugby_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scheduled_time DATETIME NOT NULL,
                    message TEXT NOT NULL)''')
                cur.execute("DELETE FROM rugby_messages")
                conn.commit()

                schedule_list = [(datetime.now(UTC_TZ),'','')] if re.match(r"Send initial schedule message: (.+)", TEXT.splitlines()[0])[1].lower() == "true" else []
                TEXT = "\n".join(TEXT.splitlines()[1:])

                games = re.split(r"\n\s*\n(?=Game \d+)", TEXT.strip())
                for game_number, game_text in enumerate(games):
                    lines = [line.strip() for line in game_text.splitlines() if line.strip()]

                    start_time = lines[1]
                    game_start = datetime.strptime(start_time, "%d-%m-%Y %H:%M").replace(tzinfo=AMSTERDAM_TZ).astimezone(UTC_TZ)

                    matchup = lines[2]
                    m = re.match(r"(.+) will be playing against (.+)!", matchup)
                    team_a = m.group(1)
                    team_b = m.group(2)

                    scheduled = []

                    # Reminders
                    scheduled.append((game_start - timedelta(hours=1, minutes=30), f"Reminder: {team_a} vs {team_b} starts in 1 hour and 30 minutes!"))
                    scheduled.append((game_start - timedelta(minutes=45), f"Reminder: {team_a} vs {team_b} starts in 45 minutes!"))
                    scheduled.append((game_start - timedelta(minutes=10), f"Reminder: {team_a} vs {team_b} starts in 10 minutes!"))

                    # Kickoff
                    scheduled.append((game_start, f"The game between {team_a} and {team_b} begins!"))
                    cur.execute("INSERT OR IGNORE INTO rugbymatches (matchname) VALUES (?)", (f"{team_a} vs {team_b}",))

                    halftime_minute = None
                    final_score_line = None
                    latest_event_time = game_start
                    for line in lines[3:]:
                        if line.startswith("Final score"):
                            final_score_line = line
                            continue
                        minute_match = re.match(r"(\d+)'", line)
                        if not minute_match:
                            if len(line) > 0:
                                scheduled.append((latest_event_time + timedelta(seconds=20), line))
                            continue
                        minute = int(minute_match.group(1))
                        if "Half-time" in line:
                            halftime_minute = minute
                            halftime_time = (game_start + timedelta(minutes=minute))
                            scheduled.append((halftime_time, line))
                            scheduled.append((halftime_time, "Second half starts in 15 minutes."))
                            resume_time = halftime_time + timedelta(minutes=15)
                            scheduled.append((resume_time, "The second half begins!"))
                            latest_event_time = max(latest_event_time, resume_time)
                            continue

                        actual_time = (game_start + timedelta(minutes=minute))

                        if halftime_minute is not None and minute > halftime_minute:
                            actual_time += timedelta(minutes=15)  # Account for halftime break

                        scheduled.append((actual_time, line))
                        latest_event_time = max(latest_event_time,actual_time)

                    # Final score 1 minute after last event
                    if final_score_line:
                        scheduled.append((game_start + timedelta(minutes=96), final_score_line))
                        schedule_list.append((game_start + timedelta(minutes=96, seconds=20),final_score_line + "\n", f"{team_a} vs {team_b} at <t:{int(game_start.timestamp())}:f>\n"))

                    # Insert into database
                    for scheduled_time, message in scheduled:
                        cur.execute("INSERT INTO rugby_messages (scheduled_time, message) VALUES (?, ?)", (scheduled_time.isoformat(), message))

                for i in range(len(schedule_list)):
                    game_schedule = "These are the matches of this round:\n\n"
                    game_schedule += "".join(schedule_list[j][1] for j in range(i+1))
                    game_schedule += "".join(schedule_list[j][2] for j in range(i+1, len(schedule_list)))
                    cur.execute("INSERT INTO rugby_messages (scheduled_time, message) VALUES (?, ?)", (schedule_list[i][0].isoformat(), game_schedule))

                conn.commit()
                conn.close()

                print("Rugby report processed and scheduled messages stored in the database.")
                os.remove(filename)
        except Exception as e:
            print(f"Error processing rugby report: {e}")
        await asyncio.sleep(10)

async def send_rugby_message(client):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            conn = sqlite3.connect("DailyGamesPosts.db")
            cur = conn.cursor()

            cur.execute("""
            SELECT id, message
            FROM rugby_messages
            WHERE scheduled_time <= ?
            ORDER BY scheduled_time
            """, (datetime.now(UTC_TZ).isoformat(),))

            messages = cur.fetchall()
            for message_id, message in messages:
                print(f"Sending scheduled rugby message: {message}")
                thread = await client.fetch_channel(DAILY_RUGBY_CHANNEL_ID)

                is_first_reminder = re.match(r"Reminder: (.+) vs (.+) starts in 1 hours and 30 minutes!", message)
                is_game_start = re.match(r"The game between (.+) and (.+) begins!", message)
                if is_first_reminder or is_game_start:
                    match_obj = re.match(r"Reminder: (.+?) vs (.+?) starts in .+!|The game between (.+?) and (.+?) begins!", message)
                    team_a = (match_obj.group(1) or match_obj.group(3)).strip()
                    team_b = (match_obj.group(2) or match_obj.group(4)).strip()
                    cur.execute("SELECT userid FROM rugbymatchsubscriptions WHERE LOWER(matchname) = LOWER(?)", (f"{team_a} vs {team_b}",))
                    user_ids = [int(row[0]) for row in cur.fetchall()]

                    if is_game_start:
                        cur.execute("DELETE FROM rugbymatchsubscriptions WHERE LOWER(matchname) = LOWER(?)", (f"{team_a} vs {team_b}",))
                        cur.execute("DELETE FROM rugbymatches WHERE LOWER(matchname) = LOWER(?)", (f"{team_a} vs {team_b}",))

                    for guild in client.guilds:
                        if guild.name == GUILD:
                            tags = []
                            for member in guild.members:
                                if member.id in user_ids:
                                    tags.append(member.mention)
                            if len(tags) > 0:
                                message += f"\nCircadians subscribed to this match: " + " ".join(tags)

                await thread.send(message)
                cur.execute("DELETE FROM rugby_messages WHERE id = ?", (message_id,))
                conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error sending rugby messages: {e}")
        await asyncio.sleep(10)

async def send_daily_date_message(client):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            today = datetime.now(UTC_TZ).strftime('%d %B')
            conn = sqlite3.connect("DailyGamesPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT date FROM latest_daily_message")
            last_date = cursor.fetchone()[0]

            if today != last_date:
                response = requests.get(ICAL_URL)
                cal = Calendar.from_ical(response.content)

                print(f"Looking for calendar events on {today}")
                for component in cal.walk():
                    if component.name == "VEVENT":
                        if component.get('dtstart').dt.strftime('%d %B') == today:
                            title = component.get('summary')
                            description = component.get('description')

                            message = f"Today ({today}) is called {title}.\n\nThis day was named by {description.split('Named by ')[1].strip().split()[0]}"

                            thread = await client.fetch_channel(DAILY_DATE_CHANNEL_ID)
                            await thread.send(message)   
                            cursor.execute("UPDATE latest_daily_message SET date = ?", (today,))             
                            conn.commit()
                            break
            conn.close()

        except Exception as e:
            print(f"Error sending daily date message: {e}")
        await asyncio.sleep(2)

intents = discord.Intents.default()
intents.members = True
client = MyClient(intents=intents)

@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('Guilds the bot is in:')
    for guild in client.guilds:
        client.tree.clear_commands(guild=guild)  # Clear global commands
        await client.tree.sync(guild=guild)  # Sync to clear guild-specific commands
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