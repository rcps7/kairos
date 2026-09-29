"""Optional Discord channel for Kairos.

Mirrors a small subset of the Telegram interface with a manual user allowlist.
Disabled unless enabled in config and a token is present (keyring/config).
Requires the privileged "Message Content" intent to be enabled in the bot.
"""

import asyncio
import logging
import threading

from kairos import config

logger = logging.getLogger(__name__)


class DiscordBot:
    def __init__(self, engine):
        self.engine = engine
        self.client = None
        self.running = False
        self.last_error = None
        self._thread = None
        self._loop = None

    def _conf(self):
        return config.load_config().get("discord", {}) or {}

    def _token(self):
        return config._keyring_get("discord_token") or self._conf().get("token")

    def allowed_ids(self):
        out = set()
        for x in (self._conf().get("allowed_user_ids") or []):
            try:
                out.add(int(str(x).strip()))
            except (TypeError, ValueError):
                continue
        return out

    def _authorized(self, user_id) -> bool:
        return user_id in self.allowed_ids()

    def start(self):
        conf = self._conf()
        if not conf.get("enabled"):
            return
        token = self._token()
        if not token:
            self.last_error = "No Discord token configured."
            logger.warning(self.last_error)
            return
        try:
            import discord
        except Exception as e:
            self.last_error = f"discord.py not installed: {e}"
            logger.warning(self.last_error)
            return

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready():  # noqa: ANN001
            self.running = True
            logger.info("Discord bot ready: %s", client.user)

        @client.event
        async def on_message(message):  # noqa: ANN001
            if message.author.bot:
                return
            if not self._authorized(message.author.id):
                logger.warning("Unauthorized Discord user %s", message.author.id)
                try:
                    await message.reply("Unauthorized.")
                except Exception:
                    pass
                return
            try:
                await self._handle(message)
            except Exception as e:
                try:
                    await message.reply(f"Error: {e}")
                except Exception:
                    pass

        self.client = client

        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                loop.run_until_complete(client.start(token))
            except Exception as e:
                self.last_error = str(e)
                logger.error("Discord bot stopped: %s", e)

        self._thread = threading.Thread(target=run, daemon=True, name="kairos-discord")
        self._thread.start()

    async def _handle(self, message):  # noqa: ANN001
        content = (message.content or "").strip()
        if not content.startswith("!"):
            return
        body = content[1:]
        cmd = body.split(maxsplit=1)[0].lower() if body else ""
        arg = body[len(cmd):].strip()
        if cmd == "help":
            await message.reply("Kairos commands: !chat <text>, !search <query>, !remember <note>")
        elif cmd == "chat":
            reply = await asyncio.to_thread(self.engine.chat, arg)
            await message.reply((reply or "")[:1900])
        elif cmd == "search":
            res = await asyncio.to_thread(self.engine.search_web, arg, 5)
            lines = [f"{i}. {r.get('title','')} {r.get('url','')}" for i, r in enumerate(res or [], 1)]
            await message.reply(("\n".join(lines) or "No results.")[:1900])
        elif cmd == "remember":
            await asyncio.to_thread(self.engine.add_memory, arg)
            await message.reply("Saved to retention.")
        else:
            await message.reply("Unknown command. Try !help")

    def stop(self):
        try:
            if self.client and self._loop:
                asyncio.run_coroutine_threadsafe(self.client.close(), self._loop)
        except Exception:
            pass
        self.running = False