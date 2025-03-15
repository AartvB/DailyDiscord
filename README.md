# DailyDiscord

DailyDiscord is a discord bot, used to do some actions in the discord server r/DailyGames Official.

This code is shared to give people insight in how this bot works. You are free to use (parts of) this code to create a discord bot of your own!

## Usage

The code cannot be run in its current state. To run it, you need to:

1. Set up a reddit bot (Create app at https://www.reddit.com/prefs/apps/)
2. Fill in the account details in a file called 'praw.ini'
3. Run the file 'fill_database_after_failure.py'
4. Create a file called '.env' with information on your discord bot and the server. Syntax:

```
DISCORD_TOKEN=token
DISCORD_GUILD=server name (I am using r/DailyGames Official)
DISCORD_CHANNEL=channel name (I am using new-post-links-🆕)
```

5. You can start running the bot by running 'Discord_bot.py'. Note that when you use Windows, you will sometimes get an error message. However, this is no problem, you can ignore that. It is a known bug with the python implementation of the discord API in Windows.

## License

MIT License

Copyright (c) 2025 AartvB

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.