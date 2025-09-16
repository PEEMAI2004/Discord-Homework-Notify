import os
import sys
import asyncio
import discord
from dotenv import load_dotenv


async def purge_channel(channel: discord.TextChannel) -> None:
    """Purge all messages in a channel, handling 14-day rule and rate limits."""
    total_deleted = 0

    # First pass: fast bulk delete for messages <= 14 days old
    try:
        deleted_recent = await channel.purge(limit=None, bulk=True, reason="Requested purge")
        count_recent = len(deleted_recent)
        total_deleted += count_recent
        print(f"🧹 Bulk-deleted (<=14d): {count_recent} messages")
        # Small pause to respect rate limits
        await asyncio.sleep(2)
    except Exception as e:
        print(f"⚠️ Bulk purge step encountered an issue: {e}")

    # Second pass: individually delete any remaining older messages
    deleted_old = 0
    try:
        async for msg in channel.history(limit=None, oldest_first=False):
            try:
                await msg.delete()
                deleted_old += 1
                # Gentle pacing; discord.py also handles rate limits internally
                await asyncio.sleep(0.2)
                if deleted_old % 100 == 0:
                    print(f"…deleted {deleted_old} older messages so far")
            except Exception as inner_e:
                print(f"⚠️ Could not delete message {msg.id}: {inner_e}")
        total_deleted += deleted_old
    except Exception as e:
        print(f"⚠️ History fetch/delete encountered an issue: {e}")

    print(f"✅ Finished. Total messages deleted: {total_deleted} (older individually: {deleted_old})")


async def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")

    # Channel ID from argv or env; fallback to provided example
    default_id = "1349073308494204938"
    chan_arg = sys.argv[1] if len(sys.argv) > 1 else os.getenv("CHANNEL_ID", default_id)
    try:
        channel_id = int(chan_arg)
    except ValueError:
        print(f"❌ Invalid channel ID: {chan_arg}")
        return

    if not token:
        print("❌ DISCORD_TOKEN not found in environment variables (.env).")
        return

    intents = discord.Intents.default()
    # Message content intent is not required for deletions via REST/history
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"✅ Logged in as {client.user}")
        try:
            channel = client.get_channel(channel_id)
            if channel is None:
                channel = await client.fetch_channel(channel_id)

            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                print(f"❌ Channel {channel_id} is not a text channel or thread.")
                await client.close()
                return

            # Ensure the bot has Manage Messages permission in this channel
            perms = channel.permissions_for(channel.guild.me) if isinstance(channel, discord.TextChannel) else None
            if isinstance(channel, discord.TextChannel) and (not perms.manage_messages):
                print("❌ Missing 'Manage Messages' permission in this channel.")
                await client.close()
                return

            print(f"🗑️ Purging all messages in #{getattr(channel, 'name', 'thread')} ({channel_id})…")
            print("ℹ️ Note: Bulk delete only applies to messages <= 14 days old. Older messages are removed individually and may take time.")

            await purge_channel(channel)
        finally:
            await client.close()

    await client.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted by user.")
