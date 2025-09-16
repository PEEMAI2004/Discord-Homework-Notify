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
# GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS_PATH", "/home/kamin/.credentials/client_secret_1077301503082-ejuu8jneruhh9cj2chcnpqq69t624eqa.apps.googleusercontent.com.json")
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

async def format_and_send_events(events, now, channel):
    # Hold message IDs to delete later
    global sent_message_ids
    if 'sent_message_ids' not in globals():
        sent_message_ids = []
    # Delete previous messages
    for msg_id in sent_message_ids:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.delete()
            await asyncio.sleep(1)  # Avoid rate limits
        except Exception as e:
            print(f"⚠️ Could not delete message ID {msg_id}: {e}")
    sent_message_ids.clear()

    try:
        bangkok_tz = ZoneInfo("Asia/Bangkok")
        msg = "## Activities\n\n"
        # Sort events by end time
        events.sort(key=lambda e: e.end.astimezone(bangkok_tz) if e.end else datetime.datetime.max)
        # Iterate through sorted events
        for event in events:
            event_end = event.end.astimezone(bangkok_tz) if event.end else None
            event_time = event_end.strftime('%d/%m/%y %H:%M') if event_end else "All day"

            if event_end:
                time_until = event_end - now.astimezone(bangkok_tz)
                total_seconds = time_until.total_seconds()

                if total_seconds > 0:
                    days, remainder = divmod(total_seconds, 86400)
                    hours, remainder = divmod(remainder, 3600)
                    minutes = remainder // 60
                    time_until_str = f"{int(days)} d, {int(hours)} hr, and {int(minutes)} min"
                else:
                    time_until_str = "Already ended"
            else:
                time_until_str = "N/A"
                
            description = event.description if hasattr(event, 'description') else "No description available"
            class_id = description.split(",")[0] if description else "Unknown Class"
            activity_id = description.split(",")[1] if len(description.split(",")) > 1 else "Unknown Activity"
            # link to the event
            baselink = os.getenv("BASE_SITE_URL").rstrip('/')
            activity_link = f"{baselink}/{class_id}/activity/{activity_id}"
            
            msg_check_point = msg
            msg += (
                f"### [{event.summary}](<{activity_link}>)\n"
                f"📆 {event_time}\n"
                f"⏳ {time_until_str}\n"
            )
            if len(msg) > 2000:  # Discord message limit
                sent_msg = await channel.send(msg_check_point)
                msg = (
                f"### [{event.summary}](<{activity_link}>)\n"
                f"📆 {event_time}\n"
                f"⏳ {time_until_str}\n"
                )
                sent_msg = await channel.send(msg)
                sent_message_ids.append(sent_msg.id)
        
        sent_msg = await channel.send(msg)
        sent_message_ids.append(sent_msg.id)
        await asyncio.sleep(1)  # Avoid rate limits
    except Exception as e:
        print(f"❌ Error sending event '{event.summary}': {e}")


# Fetch and send only events that have not ended yet
async def send_event_notifications():
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"🔎 Checking calendars at {now.isoformat()}")

    for calendar_id, channel_id in CALENDAR_MAP.items():
        try:
            gc = GoogleCalendar(calendar_id, credentials_path=GOOGLE_CREDENTIALS)
            events = list(gc.get_events(time_min=now))

            if not events:
                print(f"📭 No upcoming due date for calendar {calendar_id}")
                continue

            # Filter out events that have already ended
            upcoming_events = []
            for event in events:
                try:
                    # Assume event.end is a datetime object or has a 'dateTime' string
                    if hasattr(event, 'end'):
                        if isinstance(event.end, dict):
                            end_time = event.end.get('dateTime') or event.end.get('date')
                            end_dt = datetime.datetime.fromisoformat(end_time)
                        else:
                            end_dt = event.end if isinstance(event.end, datetime.datetime) else None
                        if end_dt and end_dt > now:
                            upcoming_events.append(event)
                except Exception as e:
                    print(f"⚠️ Skipping event due to parsing error: {e}")

            if not upcoming_events:
                print(f"⌛ No valid upcoming events for calendar {calendar_id}")
                continue

            channel = client.get_channel(channel_id)
            if not channel:
                print(f"❌ Discord channel ID {channel_id} not found.")
                continue

            print(f"📡 Sending {len(upcoming_events)} event(s) for calendar {calendar_id} to channel {channel.name} ({channel_id})")
            # for event in upcoming_events:
            #     await format_and_send_event(event, now, channel)
            await format_and_send_events(upcoming_events, now, channel)

        except Exception as e:
            print(f"❌ Error processing calendar {calendar_id}: {e}")

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
    
    # await send_event_notifications()  # Send notifications immediately on startup for testing
    await asyncio.sleep(1)

# Run the bot
if DISCORD_TOKEN:
    client.run(DISCORD_TOKEN)
else:
    print("❌ DISCORD_TOKEN not found in environment variables.")
