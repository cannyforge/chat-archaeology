import ssl
import certifi
import discord
import json
import aiohttp
import asyncio
import os
from datetime import datetime

TOKEN = os.environ.get("DISCORD_TOKEN", "")
CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", "0"))


async def main():
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)

    intents = discord.Intents.default()
    intents.message_content = True

    async with aiohttp.ClientSession(connector=connector) as session:
        client = discord.Client(intents=intents, connector=connector)

        @client.event
        async def on_ready():
            print(f"Logged in as {client.user}")
            channel = client.get_channel(CHANNEL_ID)
            if channel is None:
                print(f"Channel {CHANNEL_ID} not found. Check DISCORD_CHANNEL_ID.")
                await client.close()
                return

            print(f"Fetching messages from #{channel.name} ... (this can take a while for large channels)")
            messages = []
            async for msg in channel.history(limit=None, oldest_first=True):
                messages.append({
                    "id": str(msg.id),
                    "author": str(msg.author),
                    "author_id": str(msg.author.id),
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat(),
                    "attachments": [a.url for a in msg.attachments],
                    "embeds": [e.to_dict() for e in msg.embeds],
                })
                if len(messages) % 500 == 0:
                    ts = messages[-1]["timestamp"][:10]
                    print(f"  ... {len(messages)} messages fetched (up to {ts})")

            output_file = f"history_{channel.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)

            print(f"Saved {len(messages)} messages to {output_file}")
            await client.close()

        await client.start(TOKEN)


asyncio.run(main())
