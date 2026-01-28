# Discord Bot Commands

The Discord Homework Notify bot supports the following commands:

## `/fetch`
**Description:** Fetch activities from the external API and sync them to Google Calendar

**Usage:** `/fetch`

**Permissions:** Can only be used in channels that are mapped to a calendar in `CALENDAR_MAP`

**What it does:**
- Calls `get_activities()` from `api_bot.py`
- Fetches all activities from the external API
- Creates or updates events in Google Calendar
- Runs asynchronously without blocking the bot

**Example:**
```
User: /fetch
Bot: 🔄 Fetching activities from external API...
Bot: ✅ Successfully fetched and updated activities in Google Calendar!
```

---

## `/homework`
**Description:** Send homework notifications for the current channel

**Usage:** `/homework`

**Permissions:** Can only be used in channels that are mapped to a calendar in `CALENDAR_MAP`

**What it does:**
- Fetches upcoming events from the Google Calendar associated with the channel
- Sends formatted homework notifications in the channel
- Shows event titles, due dates, and time remaining
- Includes clickable links to activities (if `BASE_SITE_URL` is configured)

**Example:**
```
User: /homework
Bot: 📚 Fetching homework notifications...
Bot: ## Activities

### Math Assignment
📆 29/01/26 23:59
⏳ 0 d, 5 hr, and 30 min

### Science Lab Report
📆 30/01/26 18:00
⏳ 1 d, 0 hr, and 0 min

Bot: ✅ Homework notifications sent!
```

---

## Error Handling

Both commands will show an error message if used in a non-mapped channel:
```
❌ This command can only be used in homework notification channels.
```

## Technical Details

- **Command Prefix:** `/`
- **Implementation:** Uses `discord.ext.commands.Bot`
- **Required Intents:** `message_content = True`
- **Channel Validation:** Commands check if `ctx.channel.id` is in `CALENDAR_MAP.values()`
- **Async Processing:** `/fetch` runs in a separate thread to avoid blocking
