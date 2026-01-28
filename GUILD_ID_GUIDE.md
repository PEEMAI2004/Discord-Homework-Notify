# Getting Your Discord Guild/Server ID

To enable instant slash command updates during testing, you need to add your Discord server's ID to the `.env` file.

## Steps to Get Your Guild ID

1. **Enable Developer Mode in Discord:**
   - Open Discord
   - Go to **User Settings** (gear icon)
   - Go to **App Settings** → **Advanced**
   - Enable **Developer Mode**

2. **Copy Your Server ID:**
   - Right-click on your server icon (in the left sidebar)
   - Click **Copy Server ID**

3. **Add to `.env` file:**
   ```bash
   DISCORD_GUILD_ID=1234567890123456789  # Replace with your actual server ID
   ```

4. **Restart the bot:**
   - Stop the bot (Ctrl+C)
   - Run: `python3 discord-bot.py`
   - Commands will now sync instantly!

## Syncing Behavior

### With `DISCORD_GUILD_ID` set (Recommended for Testing):
- ✅ Commands sync **instantly** (1-5 seconds)
- ✅ Only visible in your specific server
- ✅ Perfect for development and testing

### Without `DISCORD_GUILD_ID` (Production):
- ⏱️ Commands sync **globally** (up to 1 hour)
- ✅ Visible in all servers where the bot is installed
- ✅ Use this for production deployment

## Verification

After setting `DISCORD_GUILD_ID` and restarting the bot, you should see:
```
🔄 Synced 2 command(s) to guild YOUR_GUILD_ID (instant)
```

Then type `/` in any channel in your server to see the commands appear immediately!
