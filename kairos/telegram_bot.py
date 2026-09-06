import asyncio
import logging
import threading

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import InvalidToken, TelegramError
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

from kairos import config

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, orchestration_engine):
        self.engine = orchestration_engine
        self.app = None
        self.running = False
        self._chat_ids = set()

    async def start(self):
        cfg = config.load_config()
        token = cfg.get("telegram_token")
        if not token:
            logger.error("Telegram token not found in config!")
            return

        try:
            self.app = ApplicationBuilder().token(token).build()

            self.app.add_handler(CommandHandler("start", self.start_command))
            self.app.add_handler(CommandHandler("chat", self.chat_command))
            self.app.add_handler(CommandHandler("search", self.search_command))
            self.app.add_handler(CommandHandler("learn", self.learn_command))
            self.app.add_handler(CommandHandler("download", self.download_command))
            self.app.add_handler(CommandHandler("skills", self.skills_command))
            self.app.add_handler(CommandHandler("runs", self.run_skill_command))
            self.app.add_handler(CommandHandler("newskill", self.new_skill_command))
            self.app.add_handler(CommandHandler("mail", self.mail_command))
            self.app.add_handler(CommandHandler("sendmail", self.send_mail_command))
            self.app.add_handler(CommandHandler("expired", self.expired_command))
            self.app.add_handler(CommandHandler("providers", self.providers_command))
            self.app.add_handler(CommandHandler("setllm", self.setllm_command))
            self.app.add_handler(CommandHandler("reflect", self.reflect_command))
            self.app.add_handler(CommandHandler("lessons", self.lessons_command))
            self.app.add_handler(CommandHandler("ports", self.ports_command))
            self.app.add_handler(CommandHandler("open", self.open_command))
            self.app.add_handler(CommandHandler("send", self.send_command))
            self.app.add_handler(CommandHandler("read", self.read_command))
            self.app.add_handler(CommandHandler("close", self.close_command))
            self.app.add_handler(CommandHandler("remember", self.remember_command))
            self.app.add_handler(CommandHandler("memory", self.memory_command))
            self.app.add_handler(CommandHandler("predict", self.predict_command))
            self.app.add_handler(CommandHandler("kill", self.kill_command))
            self.app.add_handler(CallbackQueryHandler(self.button_handler))

            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling()
            self.running = True
            logger.info("Telegram Bot started.")
        except InvalidToken:
            logger.error("Invalid Telegram bot token. Re-run the app and enter a valid token.")
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
        except Exception as e:
            logger.error(f"Unexpected Telegram error: {e}")

    async def stop(self):
        if self.app and self.running:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    def _register_chat(self, update: Update):
        if update.effective_chat:
            self._chat_ids.add(update.effective_chat.id)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._register_chat(update)
        await update.message.reply_text(
            "Kairos Agent Online.\n"
            "/chat <text> - talk to the LLM\n"
            "/search <query> - web search\n"
            "/learn <url> - scrape page and store knowledge\n"
            "/download <url> - download audio/video\n"
            "/skills - list skills\n"
            "/mail read - read email\n"
            "/expired - list items due for deletion\n"
            "/providers - list LLM providers\n"
            "/setllm <id> - switch LLM"
        )

    async def chat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        prompt = " ".join(context.args)
        if not prompt:
            await update.message.reply_text("Usage: /chat <message>")
            return
        try:
            reply = await asyncio.to_thread(self.engine.ask_llm, prompt)
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"LLM error: {e}")

    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = " ".join(context.args)
        if not query:
            await update.message.reply_text("Usage: /search <query>")
            return
        try:
            results = await asyncio.to_thread(self.engine.search_web, query, 10)
            if not results:
                await update.message.reply_text("No results found.")
                return
            lines = [f"Results for '{query}':"]
            for i, r in enumerate(results[:10], 1):
                desc = r.get("description", "").strip()
                lines.append(f"{i}. {r['title']}\n{r['url']}")
                if desc:
                    lines.append(f"   {desc}")
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"Search error: {e}")

    async def learn_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /learn <url>")
            return
        url = context.args[0]
        await update.message.reply_text(f"Scraping {url} ...")
        try:
            result = await asyncio.to_thread(self.engine.learn_from_page, url)
            await update.message.reply_text(
                f"Learned from: {result['title']}\n\n{result['summary'][:3500]}"
            )
        except Exception as e:
            await update.message.reply_text(f"Learn error: {e}")

    async def download_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /download <url>")
            return
        url = context.args[0]
        context.user_data["pending_url"] = url
        keyboard = [[
            InlineKeyboardButton("MP3 (audio)", callback_data="dl_mp3"),
            InlineKeyboardButton("MP4 (video)", callback_data="dl_mp4"),
        ]]
        await update.message.reply_text("Select format:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def skills_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        skills = self.engine.list_skills()
        if not skills:
            await update.message.reply_text("No skills loaded.")
            return
        lines = ["Skills:"]
        for s in skills:
            lines.append(f"- {s['name']}: {s['description']}")
        await update.message.reply_text("\n".join(lines))

    async def run_skill_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /runs <skill_name>")
            return
        name = context.args[0]
        try:
            result = await asyncio.to_thread(self.engine.run_skill, name)
            await update.message.reply_text(str(result))
        except Exception as e:
            await update.message.reply_text(f"Skill error: {e}")

    async def new_skill_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /newskill <name> <description>")
            return
        name = context.args[0]
        description = " ".join(context.args[1:])
        code = self.engine.generate_skill(name, description)
        context.user_data["pending_skill"] = {"name": name, "description": description, "code": code}
        keyboard = [[
            InlineKeyboardButton("Approve", callback_data="approve_skill"),
            InlineKeyboardButton("Reject", callback_data="reject_skill"),
        ]]
        await update.message.reply_text(
            f"Generated skill '{name}'. Approve?\n\n```\n{code}\n```",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def mail_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            messages = await asyncio.to_thread(self.engine.read_email, 5)
            if not messages:
                await update.message.reply_text("No email or email not configured.")
                return
            lines = ["Latest emails:"]
            for m in messages:
                lines.append(f"From: {m['from']}\nSubject: {m['subject']}\n{m['body'][:200]}")
            await update.message.reply_text("\n\n".join(lines)[:3500])
        except Exception as e:
            await update.message.reply_text(f"Email error: {e}")

    async def send_mail_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /sendmail <to> <subject> | <body>")
            return
        raw = " ".join(context.args)
        to, rest = raw.split(" ", 1)
        if "|" in rest:
            subject, body = rest.split("|", 1)
        else:
            subject, body = rest, ""
        try:
            await asyncio.to_thread(self.engine.send_email, to.strip(), subject.strip(), body.strip())
            await update.message.reply_text("Email sent.")
        except Exception as e:
            await update.message.reply_text(f"Send error: {e}")

    async def expired_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        items = self.engine.collect_expired()
        if not items:
            await update.message.reply_text("No expired items.")
            return
        await self.prompt_retention(items)

    async def prompt_retention(self, items: list):
        """Send a retention prompt with per-item delete buttons to known chats."""
        if not items or not self._chat_ids:
            return
        buttons = []
        for item in items[:20]:
            label = item["label"][:40]
            buttons.append([InlineKeyboardButton(
                f"DELETE: {label}", callback_data=f"del_{item['kind']}_{item['id']}"
            )])
        buttons.append([InlineKeyboardButton("Keep all", callback_data="keep_all")])
        text = "The following items are older than retention. Tap to delete:"
        for chat_id in list(self._chat_ids):
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(buttons)
                )
            except Exception as e:
                logger.error("Failed to send retention prompt: %s", e)

    async def providers_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        providers = self.engine.llm.providers
        active = self.engine.llm.active_provider
        if not providers:
            await update.message.reply_text("No LLM providers configured.")
            return
        lines = [f"Active: {active}"]
        for pid, p in providers.items():
            lines.append(f"- {pid} (model={p.get('model')})")
        await update.message.reply_text("\n".join(lines))

    async def setllm_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /setllm <provider_id>")
            return
        pid = context.args[0]
        if self.engine.llm.set_active(pid):
            await update.message.reply_text(f"Active LLM set to {pid}")
        else:
            await update.message.reply_text(f"Provider '{pid}' not found.")

    async def reflect_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Reflecting on recent errors ...")
        try:
            analysis = await asyncio.to_thread(self.engine.reflect)
            await update.message.reply_text(analysis[:3800])
        except Exception as e:
            await update.message.reply_text(f"Reflection error: {e}")

    async def lessons_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        lessons = self.engine.recent_lessons(5)
        if not lessons:
            await update.message.reply_text("No lessons learned yet.")
            return
        await update.message.reply_text("\n\n---\n\n".join(lessons)[:3800])

    async def ports_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            ports = await asyncio.to_thread(self.engine.list_ports)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            return
        if not ports:
            await update.message.reply_text("No serial ports found.")
            return
        lines = ["Serial ports:"]
        for p in ports:
            state = "OPEN" if p.get("open") else "closed"
            lines.append(f"- {p['device']} [{state}] {p['description']}")
        await update.message.reply_text("\n".join(lines))

    async def open_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /open <port> [baud]")
            return
        device = context.args[0]
        baud = int(context.args[1]) if len(context.args) > 1 else None
        try:
            await asyncio.to_thread(self.engine.open_port, device, baud)
            await update.message.reply_text(f"Opened {device}")
        except Exception as e:
            await update.message.reply_text(f"Open failed: {e}")

    async def send_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /send <port> <text>")
            return
        device = context.args[0]
        text = " ".join(context.args[1:])
        try:
            await asyncio.to_thread(self.engine.write_port, device, text + "\n")
            await update.message.reply_text(f"Sent to {device}")
        except Exception as e:
            await update.message.reply_text(f"Send failed: {e}")

    async def read_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /read <port>")
            return
        device = context.args[0]
        try:
            data = await asyncio.to_thread(self.engine.read_port, device)
            await update.message.reply_text(data or "(no data)")
        except Exception as e:
            await update.message.reply_text(f"Read failed: {e}")

    async def close_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /close <port>")
            return
        device = context.args[0]
        try:
            await asyncio.to_thread(self.engine.close_port, device)
            await update.message.reply_text(f"Closed {device}")
        except Exception as e:
            await update.message.reply_text(f"Close failed: {e}")

    async def remember_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        content = " ".join(context.args)
        if not content:
            await update.message.reply_text("Usage: /remember <note or fact to save>")
            return
        try:
            await asyncio.to_thread(self.engine.add_memory, content)
            await update.message.reply_text("Saved to retention.")
        except Exception as e:
            await update.message.reply_text(f"Save failed: {e}")

    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        memories = self.engine.list_memories()
        if not memories:
            await update.message.reply_text("No retained data.")
            return
        lines = ["Retained data:"]
        for mem_id, content, created in memories[:10]:
            lines.append(f"- {content[:200]}")
        await update.message.reply_text("\n".join(lines)[:3800])

    async def predict_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        question = " ".join(context.args)
        if not question:
            await update.message.reply_text("Usage: /predict <question>\n(e.g. /predict how will this affect public opinion?)")
            return
        await update.message.reply_text("Running prediction (this may take a while)...")
        try:
            result = await asyncio.to_thread(self.engine.predict, question, None, None, None, "auto")
            report = result.get("report", "")
            source = result.get("source", "?")
            await update.message.reply_text(
                f"[Prediction via {source}]\n\n{report}"[:3800]
            )
        except Exception as e:
            await update.message.reply_text(f"Prediction error: {e}")

    async def kill_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm before engaging the kill switch."""
        self._register_chat(update)
        keyboard = [[
            InlineKeyboardButton("YES - SHUT DOWN", callback_data="confirm_kill"),
            InlineKeyboardButton("Cancel", callback_data="cancel_kill"),
        ]]
        await update.message.reply_text(
            "KILL SWITCH: shut down Kairos immediately?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data

        if data in ("dl_mp3", "dl_mp4"):
            fmt = "mp3" if data == "dl_mp3" else "mp4"
            url = context.user_data.get("pending_url")
            if not url:
                await query.edit_message_text(text="No pending URL found.")
                return
            await query.edit_message_text(text=f"Downloading as {fmt.upper()} ...")
            try:
                result = await asyncio.to_thread(self.engine.download_media, url, fmt)
                await query.edit_message_text(text=f"Downloaded: {result['title']}\nSaved to: {result['path']}")
            except Exception as e:
                await query.edit_message_text(text=f"Download error: {e}")

        elif data == "approve_skill":
            pending = context.user_data.get("pending_skill")
            if not pending:
                await query.edit_message_text(text="No pending skill.")
                return
            try:
                path = self.engine.create_skill(
                    pending["name"], pending["description"], pending["code"]
                )
                await query.edit_message_text(text=f"Skill '{pending['name']}' created at {path}")
            except Exception as e:
                await query.edit_message_text(text=f"Skill creation failed: {e}")

        elif data == "reject_skill":
            context.user_data.pop("pending_skill", None)
            await query.edit_message_text(text="Skill rejected.")

        elif data == "keep_all":
            await query.edit_message_text(text="Keeping all items.")

        elif data == "confirm_kill":
            await query.edit_message_text(text="Shutting down Kairos now.")
            threading.Thread(target=self.engine.emergency_kill, daemon=True).start()

        elif data == "cancel_kill":
            await query.edit_message_text(text="Kill switch cancelled.")

        elif data.startswith("del_"):
            _, kind, item_id = data.split("_", 2)
            deleted = self.engine.approve_retention_deletion([item_id])
            await query.edit_message_text(text=f"Deleted {deleted} item(s).")
