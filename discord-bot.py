import discord
import asyncio
import datetime
from datetime import time as dtime
from discord.ext import tasks
from gcsa.google_calendar import GoogleCalendar
from dotenv import load_dotenv
import os
from zoneinfo import ZoneInfo
from api_bot import get_activities

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS_PATH")
print(f"🔑 Using Google credentials from {GOOGLE_CREDENTIALS}")

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

# Initialize Discord bot
intents = discord.Intents.default()
client = discord.Client(intents=intents)

# Constants and state for message handling
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
DISCORD_MESSAGE_LIMIT = 2000
# Track previously-sent message IDs per channel to delete cleanly next run
_PREV_MESSAGE_IDS = {}
# Track which events we've already notified about for end-time alerts
_NOTIFIED_END_ALERTS = {}


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


def _cleanup_notified(now_bkk):
    """Remove stale notification keys whose end time has passed."""
    try:
        stale = [k for k, ts in _NOTIFIED_END_ALERTS.items() if ts <= int(now_bkk.timestamp())]
        for k in stale:
            _NOTIFIED_END_ALERTS.pop(k, None)
    except Exception:
        pass


def _make_notification_key(calendar_id, event, end_bkk, hours):
    eid = getattr(event, "event_id", None) or getattr(event, "id", None)
    if not eid:
        # Fallback to a composite based on summary and end timestamp
        eid = f"{getattr(event, 'summary', 'Untitled')}:{int(end_bkk.timestamp())}"
    return f"{calendar_id}:{eid}:{hours}"


async def notify_before_event_end(hours):
    """Notify about events that end within the next `hours` hours.

    Aggregates events per channel and sends a concise list.
    Deduplicates notifications using in-memory keys across invocations.
    """
    if hours is None or hours <= 0:
        print("⚠️ notify_before_event_end called with non-positive hours; skipping")
        return

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_bkk = now_utc.astimezone(BANGKOK_TZ)
    _cleanup_notified(now_bkk)

    window_seconds = int(hours * 3600)

    # Collect events per channel
    per_channel = {}
    per_channel_keys = {}

    for calendar_id, channel_id in CALENDAR_MAP.items():
        try:
            gc = GoogleCalendar(calendar_id, credentials_path=GOOGLE_CREDENTIALS)
            events = list(gc.get_events(time_min=now_utc))
        except Exception as e:
            print(f"❌ Error fetching events for calendar {calendar_id}: {e}")
            continue

        for event in events:
            try:
                end_bkk = _safe_event_end_in_bkk(event)
                if not end_bkk:
                    continue
                delta = end_bkk - now_bkk
                seconds = int(delta.total_seconds())
                if seconds <= 0 or seconds > window_seconds:
                    continue

                key = _make_notification_key(calendar_id, event, end_bkk, hours)
                if key in _NOTIFIED_END_ALERTS:
                    continue

                per_channel.setdefault(channel_id, []).append((event, end_bkk))
                per_channel_keys.setdefault(channel_id, []).append((key, int(end_bkk.timestamp())))
            except Exception as e:
                print(f"⚠️ Skipping event due to parsing error: {e}")

    # Send notifications per channel
    for channel_id, items in per_channel.items():
        channel = await _resolve_channel(channel_id)
        if not channel:
            print(f"❌ Discord channel ID {channel_id} not found for ending-soon alerts.")
            continue

        # Sort by end time ascending
        items.sort(key=lambda pair: pair[1])

        header = f"## Activities ending within {hours} hour(s)\n\n"
        current_msg = header
        chunks = []

        for event, _end in items:
            block = _format_event_block(event, now_bkk)
            if len(current_msg) + len(block) > DISCORD_MESSAGE_LIMIT:
                chunks.append(current_msg.rstrip())
                current_msg = block
            else:
                current_msg += block

        if current_msg.strip():
            chunks.append(current_msg.rstrip())

        for content in chunks:
            try:
                await channel.send(content)
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"❌ Failed sending ending-soon alert to channel {channel_id}: {e}")

        # Mark as notified
        for key, ts in per_channel_keys.get(channel_id, []):
            _NOTIFIED_END_ALERTS[key] = ts


# Fetch and send only events that have not ended yet
async def send_event_notifications():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_bkk = now_utc.astimezone(BANGKOK_TZ)
    print(f"🔎 Checking calendars at {now_utc.isoformat()}")

    for calendar_id, channel_id in CALENDAR_MAP.items():
        await _process_calendar(calendar_id, channel_id, now_utc, now_bkk)


async def _process_calendar(calendar_id, channel_id, now_utc, now_bkk):
    try:
        gc = GoogleCalendar(calendar_id, credentials_path=GOOGLE_CREDENTIALS)
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

# Daily 9AM loop
@tasks.loop(time=dtime(9, 0))
async def check_calendar():
    # await send_event_notifications_today()
    get_activities()
    await send_event_notifications()

# On bot ready
@client.event
async def on_ready():
    # get_activities()
    print(f"✅ Logged in as {client.user}")
    if not check_calendar.is_running():
        check_calendar.start()
    await notify_before_event_end(24)
    await notify_before_event_end(12)
    await notify_before_event_end(1)
    await send_event_notifications()  # Send notifications immediately on startup for testing
    await asyncio.sleep(1)

# Run the bot
if DISCORD_TOKEN:
    client.run(DISCORD_TOKEN)
else:
    print("❌ DISCORD_TOKEN not found in environment variables.")
