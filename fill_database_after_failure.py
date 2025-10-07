## Make/fill a database filled with all the posts

import praw
import sqlite3

reddit = praw.Reddit('bot1')
reddit.validate_on_submit = True

# Database setup
conn = sqlite3.connect("DailyGamesPosts.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, seriesname TEXT DEFAULT NULL)")
cursor.execute("CREATE TABLE IF NOT EXISTS series (name TEXT PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS subscriptions (userid TEXT, seriesname TEXT, platform TEXT CHECK(platform IN ('reddit','discord')), PRIMARY KEY (seriesname, platform, userid))")
conn.commit()

# Function to fetch posts from a subreddit
subreddit = reddit.subreddit("dailygames")
for post in subreddit.new(limit=30):  # Fetches the newest posts
    cursor.execute("INSERT OR IGNORE INTO posts (id) VALUES (?)", (post.id,))
    conn.commit()

# Close the database connection
conn.close()