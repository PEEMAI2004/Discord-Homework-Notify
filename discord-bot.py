import discord
from discord.ext import commands, tasks
import asyncio
import datetime
from datetime import time as dtime
from gcsa.google_calendar import GoogleCalendar
from dotenv import load_dotenv
import os
from zoneinfo import ZoneInfo
from api_bot import get_activities

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")  # Optional: for faster command sync during testing
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS_PATH")
GCSA_TOKEN_PATH = os.getenv("GCSA_TOKEN_PATH", "/home/kamin/.credentials/token.pickle")  # Default path for gcsa token
DISCORD_BOT_STATUS_CHANEL = os.getenv("DISCORD_BOT_STATUS_CHANEL")
FETCH_ON_START = os.getenv("FETCH_ON_START", "true").lower() == "true"  # Whether to fetch API on startup
FETCH_AT_9AM = os.getenv("FETCH_AT_9AM", "true").lower() == "true"  # Whether to run scheduled fetch at 9AM
print(f"🔑 Using Google credentials from {GOOGLE_CREDENTIALS}")
print(f"⚙️ FETCH_ON_START: {FETCH_ON_START}")
print(f"⚙️ FETCH_AT_9AM: {FETCH_AT_9AM}")

# Parse CALENDAR_MAP from environment
try:
    CALENDAR_MAP = {
        cal.strip(): int(chan.strip())
        for cal, chan in (pair.split(":") for pair in os.getenv("CALENDAR_MAP", "").split(",") if pair.strip())
    }
except Exception as e:
    print(f"❌ Error parsing CALENDAR_MAP: {e}")
    CALENDAR_MAP = {}

if not CALENDAR_MAP:
    print("⚠️ No valid calendar-channel mappings found in CALENDAR_MAP.")

# Initialize Discord bot with commands support
intents = discord.Intents.default()
intents.message_content = True  # Required for commands
client = commands.Bot(command_prefix='/', intents=intents)

# Constants and state for message handling
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
DISCORD_MESSAGE_LIMIT = 2000
# Track previously-sent message IDs per channel to delete cleanly next run
_PREV_MESSAGE_IDS = {}


def _safe_event_end_in_bkk(event):
    """Return event end as aware datetime in Bangkok tz, or None.

    Handles cases where event.end may be a datetime, dict with 'dateTime'/'date',
    or missing/naive. For all-day (date-only) events, returns None.
    """
    try:
        end = getattr(event, "end", None)
        if not end:
            return None
        # Dict shape from some calendar libs
        if isinstance(end, dict):
            end_time = end.get("dateTime") or end.get("date")
            if not end_time:
                return None
            # If only a date is provided, treat as all-day -> None
            if "T" not in end_time:
                return None
            dt = datetime.datetime.fromisoformat(end_time)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(BANGKOK_TZ)
        # Datetime path
        if isinstance(end, datetime.datetime):
            if end.tzinfo is None:
                end = end.replace(tzinfo=datetime.timezone.utc)
            return end.astimezone(BANGKOK_TZ)
    except Exception:
        pass
    return None


def _format_time_until(event_end_bkk, now_bkk):
    if not event_end_bkk:
        return "N/A"
    delta = event_end_bkk - now_bkk
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return "Already ended"
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    return f"{int(days)} d, {int(hours)} hr, and {int(minutes)} min"


def _build_activity_link(description):
    """Return (link, class_id, activity_id) built from description and BASE_SITE_URL.

    Description expected format: "<class_id>,<activity_id>,...". Falls back to
    'Unknown Class' / 'Unknown Activity' if missing. If BASE_SITE_URL is not
    set, returns (None, class_id, activity_id).
    """
    desc = (getattr(description, "strip", lambda: description)() or "") if description else ""
    parts = [p.strip() for p in desc.split(",") if p is not None]
    class_id = parts[0] if len(parts) > 0 and parts[0] else "Unknown Class"
    activity_id = parts[1] if len(parts) > 1 and parts[1] else "Unknown Activity"

    base = (os.getenv("BASE_SITE_URL") or "").strip()
    if not base:
        return None, class_id, activity_id
    base = base.rstrip("/")
    return f"{base}/{class_id}/activity/{activity_id}", class_id, activity_id


def _format_event_block(event, now_bkk):
    end_bkk = _safe_event_end_in_bkk(event)
    event_time = end_bkk.strftime("%d/%m/%y %H:%M") if end_bkk else "All day"
    time_until_str = _format_time_until(end_bkk, now_bkk)

    summary = getattr(event, "summary", "Untitled")
    link, _, _ = _build_activity_link(getattr(event, "description", None))
    title = f"### [{summary}](<{link}>)\n" if link else f"### {summary}\n"

    return (
        f"{title}"
        f"📆 {event_time}\n"
        f"⏳ {time_until_str}\n"
    )


async def format_and_send_events(events, now, channel):
    """Format events and send to the given Discord channel.

    - Deletes messages previously sent by this function for the channel.
    - Sorts events by end time in Bangkok tz.
    - Chunks output to respect Discord 2000-char limit.
    """
    # Delete previously sent messages for this channel
    channel_ids = _PREV_MESSAGE_IDS.get(channel.id, [])
    if channel_ids:
        for msg_id in channel_ids:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.delete()
                await asyncio.sleep(0.5)  # Tread lightly re: rate limits
            except Exception as e:
                print(f"⚠️ Could not delete message ID {msg_id} in channel {channel.id}: {e}")
    _PREV_MESSAGE_IDS[channel.id] = []

    try:
        now_bkk = now.astimezone(BANGKOK_TZ)

        # Sort events by end time (None -> far future to send last)
        events.sort(key=lambda e: _safe_event_end_in_bkk(e) or datetime.datetime.max.replace(tzinfo=BANGKOK_TZ))

        header = "## Activities\n\n"
        current_msg = header
        chunks = []

        for event in events:
            block = _format_event_block(event, now_bkk)
            if len(current_msg) + len(block) > DISCORD_MESSAGE_LIMIT:
                # Push the current chunk and start a new one without repeating header
                chunks.append(current_msg.rstrip())
                current_msg = block
            else:
                current_msg += block

        if current_msg.strip():
            chunks.append(current_msg.rstrip())

        # Send chunks and remember their IDs for later cleanup
        for content in chunks:
            sent = await channel.send(content)
            _PREV_MESSAGE_IDS[channel.id].append(sent.id)
            await asyncio.sleep(0.5)  # Avoid rate limits

    except Exception as e:
        ch = getattr(channel, "id", "unknown")
        print(f"❌ Error sending events for channel {ch}: {e}")


# Fetch and send only events that have not ended yet
async def send_event_notifications():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_bkk = now_utc.astimezone(BANGKOK_TZ)
    print(f"🔎 Checking calendars at {now_utc.isoformat()}")

    for calendar_id, channel_id in CALENDAR_MAP.items():
        await _process_calendar(calendar_id, channel_id, now_utc, now_bkk)


async def _process_calendar(calendar_id, channel_id, now_utc, now_bkk):
    try:
        gc = GoogleCalendar(calendar_id, credentials_path=GOOGLE_CREDENTIALS, token_path=GCSA_TOKEN_PATH)
        events = list(gc.get_events(time_min=now_utc))

        if not events:
            print(f"📭 No events returned for calendar {calendar_id}")
            return

        # Filter out events that have already ended (using Bangkok tz consistency)
        upcoming_events = []
        for event in events:
            try:
                end_bkk = _safe_event_end_in_bkk(event)
                if end_bkk and end_bkk > now_bkk:
                    upcoming_events.append(event)
            except Exception as e:
                print(f"⚠️ Skipping event due to parsing error: {e}")

        if not upcoming_events:
            print(f"⌛ No valid upcoming events for calendar {calendar_id}")
            return

        channel = await _resolve_channel(channel_id)
        if not channel:
            print(f"❌ Discord channel ID {channel_id} not found.")
            return

        print(
            f"📡 Sending {len(upcoming_events)} event(s) for calendar {calendar_id} "
            f"to channel {getattr(channel, 'name', 'unknown')} ({channel_id})"
        )
        await format_and_send_events(upcoming_events, now_utc, channel)

    except Exception as e:
        print(f"❌ Error processing calendar {calendar_id}: {e}")


async def _resolve_channel(channel_id):
    ch = client.get_channel(channel_id)
    if ch:
        return ch
    try:
        return await client.fetch_channel(channel_id)
    except Exception as e:
        print(f"⚠️ fetch_channel failed for {channel_id}: {e}")
        return None

async def send_startup_message():
    """Send a startup message to all configured channels."""
    now_bkk = datetime.datetime.now(BANGKOK_TZ)
    startup_time = now_bkk.strftime("%d/%m/%Y %H:%M:%S")
    
    print(f"📢 Sending startup message to status channel")
    
    try:
        channel = await _resolve_channel(int(DISCORD_BOT_STATUS_CHANEL))
        if not channel:
            print(f"❌ Could not find status channel {DISCORD_BOT_STATUS_CHANEL} for startup message")
            return
        
        # Build list of monitored calendars
        calendar_list = "\n".join([f"  • `{cal_id}`" for cal_id in CALENDAR_MAP.keys()])
        
        message = (
            f"🤖 **Bot Online**\n\n"
            f"✅ Discord Homework Notify bot is now running!\n"
            f"⏰ Started at: {startup_time} (Bangkok Time)\n\n"
            f"📅 Monitoring {len(CALENDAR_MAP)} calendar(s):\n{calendar_list}\n\n"
            f"🔔 Daily notifications at 9:00 AM Bangkok time\n"
        )
        
        await channel.send(message)
        print(f"✉️ Startup message sent to channel {channel.name} ({DISCORD_BOT_STATUS_CHANEL})")
        await asyncio.sleep(0.5)  # Rate limit protection
        
    except Exception as e:
        print(f"❌ Error sending startup message to status channel {DISCORD_BOT_STATUS_CHANEL}: {e}")


# Discord Application Commands (Slash Commands)

@client.tree.command(name="fetch", description="Fetch activities from external API to Google Calendar")
async def fetch(interaction: discord.Interaction):
    """Fetch activities to calendar - only works in mapped channels"""
    # Check if command is used in a mapped channel
    if interaction.channel.id not in CALENDAR_MAP.values():
        await interaction.response.send_message("❌ This command can only be used in homework notification channels.", ephemeral=True)
        return
    
    await interaction.response.send_message("🔄 Fetching activities from external API...")
    
    try:
        # Run get_activities in a thread to avoid blocking
        await asyncio.to_thread(get_activities)
        await interaction.followup.send("✅ Successfully fetched and updated activities in Google Calendar!")
    except Exception as e:
        await interaction.followup.send(f"❌ Error fetching activities: {e}")
        print(f"❌ Error in /fetch command: {e}")


@client.tree.command(name="homework", description="Send homework notifications for this channel")
async def homework(interaction: discord.Interaction):
    """Notify homework for this channel - only works in mapped channels"""
    # Check if command is used in a mapped channel
    if interaction.channel.id not in CALENDAR_MAP.values():
        await interaction.response.send_message("❌ This command can only be used in homework notification channels.", ephemeral=True)
        return
    
    # Find the calendar ID for this channel
    calendar_id = None
    for cal_id, chan_id in CALENDAR_MAP.items():
        if chan_id == interaction.channel.id:
            calendar_id = cal_id
            break
    
    if not calendar_id:
        await interaction.response.send_message("❌ No calendar mapping found for this channel.", ephemeral=True)
        return
    
    await interaction.response.send_message("📚 Fetching homework notifications...")
    
    try:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_bkk = now_utc.astimezone(BANGKOK_TZ)
        
        # Process just this channel's calendar
        await _process_calendar(calendar_id, interaction.channel.id, now_utc, now_bkk)
        await interaction.followup.send("✅ Homework notifications sent!")
    except Exception as e:
        await interaction.followup.send(f"❌ Error sending homework notifications: {e}")
        print(f"❌ Error in /homework command: {e}")


# Daily 9AM loop
@tasks.loop(time=dtime(9, 0))
async def check_calendar():
    if FETCH_AT_9AM:
        print("🔄 Running scheduled 9AM fetch...")
        get_activities()
    else:
        print("⏭️ Skipping 9AM fetch (FETCH_AT_9AM=false)")
    await send_event_notifications()

# On bot ready
@client.event
async def on_ready():

    print(f"✅ Logged in as {client.user}")
    
    # Sync slash commands with Discord
    try:
        if DISCORD_GUILD_ID:
            # Guild-specific sync (instant updates, recommended for testing)
            guild = discord.Object(id=int(DISCORD_GUILD_ID))
            client.tree.copy_global_to(guild=guild)
            synced = await client.tree.sync(guild=guild)
            print(f"🔄 Synced {len(synced)} command(s) to guild {DISCORD_GUILD_ID} (instant)")
        else:
            # Global sync (takes up to 1 hour to propagate)
            synced = await client.tree.sync()
            print(f"🔄 Synced {len(synced)} command(s) globally (may take up to 1 hour)")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")
    
    if not check_calendar.is_running():
        check_calendar.start()
    
    await send_startup_message()
    
    if FETCH_ON_START:
        print("🚀 Running startup fetch (FETCH_ON_START=true)...")
        get_activities()
    else:
        print("⏭️ Skipping startup fetch (FETCH_ON_START=false)")
    
    await send_event_notifications()
    await asyncio.sleep(1)

# Run the bot
if DISCORD_TOKEN:
    client.run(DISCORD_TOKEN)
else:
    print("❌ DISCORD_TOKEN not found in environment variables.")
