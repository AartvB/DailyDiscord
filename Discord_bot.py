import os
from xmlrpc import client
import discord
import asyncio
from dotenv import load_dotenv
import asyncpraw
import sqlite3
import time
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from icalendar import Calendar
from rugby_class import RugbyOddsCalculator

AMSTERDAM_TZ = ZoneInfo("Europe/Amsterdam")
UTC_TZ = ZoneInfo("UTC")

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
NEW_POST_CHANNEL_ID = os.getenv('NEW_POST_CHANNEL_ID')
BOT_DOMAIN_CHANNEL_ID = os.getenv('BOT_DOMAIN_CHANNEL_ID')
DAILY_RUGBY_CHANNEL_ID = os.getenv('DAILY_RUGBY_CHANNEL_ID')
DAILY_DATE_CHANNEL_ID = os.getenv('DAILY_DATE_CHANNEL_ID')
TEST_CHANNEL_ID = os.getenv('TEST_CHANNEL_ID')
ADVERTISEMENT_CHANNEL_ID = os.getenv('ADVERTISEMENT_CHANNEL_ID')
ICAL_URL = os.getenv('ICAL_URL')

# Autocomplete helpers
async def autocomplete_subscribe_rugby_matches(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    with sqlite3.connect("DailyGamesPosts.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT matchname FROM rugbymatches WHERE LOWER(matchname) LIKE ? AND matchname NOT IN (SELECT matchname FROM rugbymatchsubscriptions WHERE userid = ?) ORDER BY matchname", (f"{current.lower()}%", user_id))
        return [discord.app_commands.Choice(name=row[0], value=row[0]) for row in cursor.fetchall()]

async def autocomplete_unsubscribe_rugby_matches(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    with sqlite3.connect("DailyGamesPosts.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT matchname FROM rugbymatchsubscriptions WHERE userid = ? AND LOWER(matchname) LIKE ? ORDER BY matchname", (user_id, f"{current.lower()}%"))
        return [discord.app_commands.Choice(name=row[0], value=row[0]) for row in cursor.fetchall()]

async def autocomplete_subscribe(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    with sqlite3.connect("DailyGamesPosts.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM series WHERE LOWER(name) LIKE ? AND name NOT IN (SELECT seriesname FROM subscriptions WHERE userid = ? AND platform = 'discord') ORDER BY name LIMIT 25", (f"{current.lower()}%", user_id))
        return [discord.app_commands.Choice(name=row[0], value=row[0]) for row in cursor.fetchall()]

async def autocomplete_unsubscribe(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    with sqlite3.connect("DailyGamesPosts.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT seriesname FROM subscriptions WHERE userid = ? AND LOWER(seriesname) LIKE ? AND platform = 'discord' ORDER BY seriesname LIMIT 25", (user_id, f"{current.lower()}%"))
        return [discord.app_commands.Choice(name=row[0], value=row[0]) for row in cursor.fetchall()]

async def autocomplete_all_series(interaction: discord.Interaction, current: str):
    with sqlite3.connect("DailyGamesPosts.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM series WHERE LOWER(name) LIKE ? ORDER BY name LIMIT 25", (f"{current.lower()}%",))
        return [discord.app_commands.Choice(name=row[0], value=row[0]) for row in cursor.fetchall()]

async def autocomplete_rugby_team(interaction: discord.Interaction, current: str):
    with sqlite3.connect("rugby.db") as conn:
        cursor = conn.cursor()
        current_round = cursor.execute('SELECT round FROM bot_round').fetchone()[0]
        cursor.execute('SELECT teamA, teamB FROM planned_matches WHERE round = ?', (current_round,))
        matches = cursor.fetchall()
        countries = set()
        for match in matches:
            cursor.execute('SELECT country FROM teams WHERE username = ?', (match[0],))
            countries.add(cursor.fetchone()[0])
            cursor.execute('SELECT country FROM teams WHERE username = ?', (match[1],))
            countries.add(cursor.fetchone()[0])
        return [discord.app_commands.Choice(name=country, value=country) for country in sorted(list(countries)) if country.lower().startswith(current.lower())]

async def autocomplete_rugby_tactic(interaction: discord.Interaction, current: str):
    return [discord.app_commands.Choice(name=tactic, value=tactic) for tactic in ["general", "insight", "physique", "technique"] if tactic.lower().startswith(current.lower())]

class MyClient(discord.Client):
    async def setup_hook(self):
        self.reddit = asyncpraw.Reddit('bot1')
        self.subreddit = await self.reddit.subreddit("dailygames")
        self.bg_task = self.loop.create_task(background_task(self))
        self.txt_task = self.loop.create_task(process_txt_files(self))
        self.rugby_task = self.loop.create_task(activate_rugby_report(self))
        self.rugby_message_task = self.loop.create_task(send_rugby_message(self))
        self.date_task = self.loop.create_task(send_daily_date_message(self))
        self.tree = discord.app_commands.CommandTree(self)

        @self.tree.command(name="subscribe", description="Subscribe to a DailyGame")
        @discord.app_commands.describe(text="The series to subscribe to")
        @discord.app_commands.autocomplete(text=autocomplete_subscribe)
        async def subscribe(interaction: discord.Interaction, text: str):
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
            except Exception as e:
                print(f"Error in subscribe: {e}")
                await interaction.response.send_message(f"An error occurred while subscribing: {e}.", ephemeral=True)

        @self.tree.command(name="unsubscribe", description="Unsubscribe from a DailyGame")
        @discord.app_commands.describe(text="The series to unsubscribe from")
        @discord.app_commands.autocomplete(text=autocomplete_unsubscribe)
        async def unsubscribe(interaction: discord.Interaction, text: str):
            user_id = interaction.user.id
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
            except Exception as e:
                print(f"Error in unsubscribe: {e}")
                await interaction.response.send_message(f"An error occurred while unsubscribing: {e}.", ephemeral=True)

        @self.tree.command(name="subscriptions", description="Show all DailyGames you are subscribed to")
        async def viewSubscriptions(interaction: discord.Interaction):
            user_id = interaction.user.id
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
            except Exception as e:
                print(f"Error in viewSubscriptions: {e}")
                await interaction.response.send_message(f"An error occurred while viewing subscriptions: {e}.", ephemeral=True)

        @self.tree.command(name="rugbysubscribe", description="Subscribe to a rugby match")
        @discord.app_commands.describe(text="The match to subscribe to")
        @discord.app_commands.autocomplete(text=autocomplete_subscribe_rugby_matches)
        async def rugbysubscribe(interaction: discord.Interaction, text: str):
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
            except Exception as e:
                print(f"Error in rugbysubscribe: {e}")
                await interaction.response.send_message(f"An error occurred while subscribing: {e}.", ephemeral=True)

        @self.tree.command(name="rugbyunsubscribe", description="Unsubscribe from a rugby match")
        @discord.app_commands.describe(text="The match to unsubscribe from")
        @discord.app_commands.autocomplete(text=autocomplete_unsubscribe_rugby_matches)
        async def rugbyunsubscribe(interaction: discord.Interaction, text: str):
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
            except Exception as e:
                print(f"Error in rugbyunsubscribe: {e}")
                await interaction.response.send_message(f"An error occurred while unsubscribing: {e}.", ephemeral=True)

        @self.tree.command(name="getrugbyodds", description="Get the odds for a rugby team to score within a certain range")
        @discord.app_commands.describe(team="The team to get odds for")
        @discord.app_commands.describe(min_points="The minimum points to consider")
        @discord.app_commands.describe(max_points="The maximum points to consider")
        @discord.app_commands.describe(tactic="The tactic to consider")
        @discord.app_commands.describe(opponent_tactic="The tactic of the opponent")
        @discord.app_commands.describe(private="Whether the result should be private")
        @discord.app_commands.autocomplete(team=autocomplete_rugby_team)
        @discord.app_commands.autocomplete(tactic=autocomplete_rugby_tactic)
        @discord.app_commands.autocomplete(opponent_tactic=autocomplete_rugby_tactic)
        async def getrugbyodds(interaction: discord.Interaction, team: str, min_points: int = None, max_points: int = None, tactic: str = None, opponent_tactic: str = None, private: bool = True):
            try:
                roc = RugbyOddsCalculator()
                result = roc.get_score_odds(team, min_points, max_points, tactic, opponent_tactic)

                tactic_str = f"the {tactic} tactic" if tactic else "no tactic"
                opponent_tactic_str = f"the {opponent_tactic} tactic" if opponent_tactic else "no tactic"

                if min_points is None and max_points is None:
                    await interaction.response.send_message(f"The odds for {team} (using {tactic_str}) to score at least 0 points against {result[0]} (using {opponent_tactic_str}) are: {result[1]}", ephemeral=private)
                elif min_points is None:
                    await interaction.response.send_message(f"The odds for {team} (using {tactic_str}) to score no more than {max_points} points against {result[0]} (using {opponent_tactic_str}) are: {result[1]}", ephemeral=private)
                elif max_points is None:
                    await interaction.response.send_message(f"The odds for {team} (using {tactic_str}) to score at least {min_points} points against {result[0]} (using {opponent_tactic_str}) are: {result[1]}", ephemeral=private)
                else:
                    await interaction.response.send_message(f"The odds for {team} (using {tactic_str}) to score at least {min_points} and no more than {max_points} points against {result[0]} (using {opponent_tactic_str}) are: {result[1]}", ephemeral=private)

            except Exception as e:
                print(f"Error in getrugbyodds: {e}")
                await interaction.response.send_message(f"An error occurred while fetching the odds: {e}.", ephemeral=True)

        @self.tree.command(name="addseries", description="Add a new DailyGame to subscribe to")
        @discord.app_commands.describe(text="The name of the new series")
        @discord.app_commands.checks.has_role('Human Overlord')
        async def addSeries(interaction: discord.Interaction, text: str):
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
                    thread = await client.fetch_channel(NEW_POST_CHANNEL_ID)
                    await thread.send(f"It is now possible to subscribe to the series named {text}!")
                conn.close()
            except Exception as e:
                print(f"Error in addSeries: {e}")
                await interaction.response.send_message(f"An error occurred while adding the series: {e}.", ephemeral=True)

        @self.tree.command(name="renameseries", description="Rename a DailyGame")
        @discord.app_commands.describe(old_name="The current name of the series", new_name="The new name for the series")
        @discord.app_commands.autocomplete(old_name=autocomplete_all_series)
        @discord.app_commands.checks.has_role('Human Overlord')
        async def renameSeries(interaction: discord.Interaction, old_name: str, new_name: str):
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
                        thread = await client.fetch_channel(NEW_POST_CHANNEL_ID)
                        await thread.send(f"The series '{old_name}' has been renamed to '{new_name}'.")
                conn.close()
            except Exception as e:
                print(f"Error in renameSeries: {e}")
                await interaction.response.send_message(f"An error occurred while renaming the series: {e}.", ephemeral=True)

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
                        thread = await client.fetch_channel(NEW_POST_CHANNEL_ID)
                        # Find the original bot message about this post
                        async for msg in thread.history(limit=50):
                            if postid in msg.content and msg.author == client.user:
                                tags = [f"<@{uid}>" for uid in user_ids]
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
            except Exception as e:
                print(f"Error in addposttoseries: {e}")
                await interaction.response.send_message(f"An error occurred while adding the post to the series: {e}.", ephemeral=True)

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
        
        @self.tree.command(name="detectad", description="Let me know when you found a reddit post containing an advertisement")
        @discord.app_commands.describe(post_link="The link to the reddit post containing the advertisement")
        async def detectad(interaction: discord.Interaction, post_link: str):
            match = re.search(r'reddit\.com/r/dailygames/comments/([a-z0-9]+)', post_link)
            if not match:
                await interaction.response.send_message("Invalid Reddit link format. Please provide a link to a DailyGames reddit post.", ephemeral=True)
                return
            postid = match.group(1)

            try:
                post = await self.reddit.submission(postid)
                post_time = post.created_utc
                with sqlite3.connect("DailyGamesPosts.db") as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT timestamp FROM latest_ad")
                    latest_ad_timestamp = cursor.fetchone()[0]
                    if post_time < latest_ad_timestamp:
                        await interaction.response.send_message("This post is older than the latest advertisement I have recorded.", ephemeral=True)
                        return
                    if post_time == latest_ad_timestamp:
                        await interaction.response.send_message("This post was already reported as an advertisement.", ephemeral=True)
                        return
                    cursor.execute("UPDATE latest_ad SET timestamp = ?", (post_time,))
                delta = int(post_time - latest_ad_timestamp); days, rem = divmod(delta, 24 * 60 * 60); hours, rem = divmod(rem, 60 * 60); minutes, seconds = divmod(rem, 60)
                thread = await self.fetch_channel(ADVERTISEMENT_CHANNEL_ID)
                await thread.send(f"A new advertisement was posted on r/dailygames. It has been {int(days)} days, {int(hours)} hours, {int(minutes)} minutes, and {int(seconds)} seconds since the last one.")
                await interaction.response.send_message(f"Thank you for reporting the advertisement. I have recorded it and notified the appropriate channel.", ephemeral=True)
            except Exception as e:
                print(f"Error in detectad: {e}")
                await interaction.response.send_message(f"An error occurred while processing the advertisement: {e}.", ephemeral=True)

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
            else:
                message += f"\nI think it is part of the series named {matched_series[0]}."
                cursor.execute("INSERT INTO posts (id, seriesname) VALUES (?, ?)", (post.id,matched_series[0]))
                cursor.execute("SELECT userid FROM subscriptions WHERE LOWER(seriesname) = LOWER(?) AND platform = 'discord'", (matched_series[0],))
                user_ids = [int(row[0]) for row in cursor.fetchall()]
                tags = [f"<@{uid}>" for uid in user_ids]
                if len(tags) > 0:
                    message += f"\nCircadians subscribed to this DailyGame: " + " ".join(tags)
            conn.commit()
            thread = await client.fetch_channel(NEW_POST_CHANNEL_ID)
            await thread.send(message)
    conn.close()

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
                thread = await client.fetch_channel(BOT_DOMAIN_CHANNEL_ID)
                # Discord messages have a 2000 character limit
                for chunk in [content[i:i+2000] for i in range(0, len(content), 2000)]:
                    await thread.send(chunk)
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

                now = datetime.now(UTC_TZ)
                schedule_list = [(now,'','')] if re.match(r"Send initial schedule message: (.+)", TEXT.splitlines()[0])[1].lower() == "true" else []

                include_messages_from_past = re.match(r"Include messages from past: (.+)", TEXT.splitlines()[1])[1].lower() == "true"
                TEXT = "\n".join(TEXT.splitlines()[2:])

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
                    if game_start > now:
                        cur.execute("INSERT OR IGNORE INTO rugbymatches (matchname) VALUES (?)", (f"{team_a} vs {team_b}",))

                    halftime_minute = None
                    final_score_line = None
                    latest_event_time = game_start
                    for line in lines[3:]:
                        if line.startswith("Final score"):
                            final_score_line = line
                            latest_event_time = max(latest_event_time, game_start + timedelta(minutes=96))
                            continue
                        minute_match = re.match(r"(\d+)'", line)
                        if not minute_match:
                            second_match = re.match(r"\+(\d+) - (.*)", line)
                            if second_match:
                                second = int(second_match.group(1))
                                message = second_match.group(2)
                                scheduled.append((latest_event_time + timedelta(seconds=second), message))
                            elif len(line) > 0:
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
                        if scheduled_time >= now or include_messages_from_past:
                            cur.execute("INSERT INTO rugby_messages (scheduled_time, message) VALUES (?, ?)", (scheduled_time.isoformat(), message))

                for i in range(len(schedule_list)):
                    if schedule_list[i][0] >= now or include_messages_from_past:
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
            thread = await client.fetch_channel(TEST_CHANNEL_ID)
            await thread.send(f"Error processing rugby report: {e}")
        await asyncio.sleep(60)

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

                is_first_reminder = re.match(r"Reminder: (.+) vs (.+) starts in 1 hour and 30 minutes!", message)
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

                    tags = [f"<@{uid}>" for uid in user_ids]
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
                response = await asyncio.to_thread(requests.get, ICAL_URL)
                cal = Calendar.from_ical(response.content)
                del response

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
        await asyncio.sleep(60)

intents = discord.Intents.default()
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