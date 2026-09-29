import asyncio
import logging
import re
import threading

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import InvalidToken, TelegramError
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

from kairos import config

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_\-]{30,}$")


def validate_token_format(token: str) -> bool:
    """Basic shape check for a Telegram bot token (id:secret)."""
    return bool(TOKEN_RE.match((token or "").strip()))


class TelegramBot:
    def __init__(self, orchestration_engine):
        self.engine = orchestration_engine
        self.app = None
        self.running = False
        self.last_error = None
        self._chat_ids = set()

    async def start(self):
        cfg = config.load_config()
        token = (cfg.get("telegram_token") or "").strip()
        if not token:
            self.last_error = "No Telegram token configured."
            logger.error("Telegram token not found. Set it in Edit -> Telegram Settings.")
            return
        if not validate_token_format(token):
            self.last_error = ("Telegram token format looks wrong (expected "
                               "'<digits>:<secret>').")
            logger.error("Telegram token format is invalid. Fix it in Edit -> Telegram Settings.")
            return

        try:
            self.app = ApplicationBuilder().token(token).build()

            commands = [
                ("start", self.start_command),
                ("chat", self.chat_command),
                ("search", self.search_command),
                ("learn", self.learn_command),
                ("download", self.download_command),
                ("skills", self.skills_command),
                ("runs", self.run_skill_command),
                ("newskill", self.new_skill_command),
                ("mail", self.mail_command),
                ("sendmail", self.send_mail_command),
                ("expired", self.expired_command),
                ("providers", self.providers_command),
                ("setllm", self.setllm_command),
                ("reflect", self.reflect_command),
                ("lessons", self.lessons_command),
                ("ports", self.ports_command),
                ("open", self.open_command),
                ("send", self.send_command),
                ("read", self.read_command),
                ("close", self.close_command),
                ("remember", self.remember_command),
                ("memory", self.memory_command),
                ("predict", self.predict_command),
                ("character", self.character_command),
                ("setcharacter", self.setcharacter_command),
                ("graph", self.graph_command),
                ("graphstats", self.graphstats_command),
                ("graphdel", self.graphdel_command),
                ("pending", self.pending_command),
                ("usage", self.usage_command),
                ("tasks", self.tasks_command),
                ("task", self.task_command),
                ("deltask", self.deltask_command),
                ("plans", self.plans_command),
                ("newplan", self.newplan_command),
                ("plan", self.plan_command),
                ("image", self.image_command),
                ("kill", self.kill_command),
            ]
            for name, handler in commands:
                self.app.add_handler(CommandHandler(name, self._guard(handler)))
            self.app.add_handler(CommandHandler("whoami", self.whoami_command))
            self.app.add_handler(CallbackQueryHandler(self._guard_cb(self.button_handler)))

            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling()
            self.running = True
            self.last_error = None
            logger.info("Telegram Bot started.")
        except InvalidToken:
            self.last_error = ("Telegram rejected the token (401 Unauthorized). Create or "
                               "regenerate it with @BotFather, then set it in "
                               "Edit -> Telegram Settings.")
            logger.error(self.last_error)
        except TelegramError as e:
            self.last_error = f"Telegram error: {e}"
            logger.error(self.last_error)
        except Exception as e:
            self.last_error = f"Unexpected Telegram error: {e}"
            logger.error(self.last_error)

    async def stop(self):
        if self.app and self.running:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    # ------------------------------------------------------------------
    # Authorization (manual allowlist)
    # ------------------------------------------------------------------
    def _allowed_ids(self):
        try:
            cfg = config.load_config().get("telegram", {}) or {}
            out = set()
            for x in cfg.get("allowed_user_ids", []) or []:
                try:
                    out.add(int(str(x).strip()))
                except (TypeError, ValueError):
                    continue
            return out
        except Exception:
            return set()

    def _authorized(self, update: Update) -> bool:
        try:
            uid = update.effective_user.id if update.effective_user else None
        except Exception:
            uid = None
        return uid is not None and uid in self._allowed_ids()

    def _guard(self, handler):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not self._authorized(update):
                uid = update.effective_user.id if update.effective_user else "?"
                logger.warning("Unauthorized Telegram command from user id %s", uid)
                try:
                    await update.message.reply_text(
                        "Unauthorized. Ask the owner to add your Telegram user ID "
                        f"({uid}) to the allowlist (send /whoami to see it).")
                except Exception:
                    pass
                return
            return await handler(update, context)
        return wrapper

    def _guard_cb(self, handler):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not self._authorized(update):
                try:
                    await update.callback_query.answer("Unauthorized.", show_alert=True)
                except Exception:
                    pass
                return
            return await handler(update, context)
        return wrapper

    async def whoami_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else "?"
        await update.message.reply_text(
            f"Your Telegram user ID is {uid}. "
            "Add it in Kairos -> Edit -> Telegram Settings -> Allowed user IDs.")

    def _register_chat(self, update: Update):
        if not self._authorized(update):
            return
        if update.effective_chat:
            self._chat_ids.add(update.effective_chat.id)

    def _capability_denied(self, capability: str):
        """Return a refusal message if the active character lacks the capability."""
        try:
            if self.engine.can(capability):
                return None
        except Exception:
            return None
        prof = self.engine.characters.active()
        return (
            f"'{prof.get('name', 'The active character')}' is not permitted to "
            f"use this capability ({capability.replace('_', ' ')})."
        )

    async def character_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        prof = self.engine.characters.active()
        lines = [f"Active character: {prof.get('name', self.engine.active_character)}"]
        if prof.get("description"):
            lines.append(prof["description"])
        lines.append("")
        lines.append("Available characters:")
        for p in self.engine.list_characters():
            mark = "*" if p["id"] == self.engine.active_character else "-"
            lines.append(f"{mark} {p['id']}  \u2014  {p['name']}")
        lines.append("")
        lines.append("Switch with: /setcharacter <id>")
        await update.message.reply_text("\n".join(lines)[:3800])

    async def setcharacter_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /setcharacter <id>")
            return
        cid = context.args[0].strip().lower()
        try:
            prof = await asyncio.to_thread(self.engine.set_character, cid)
        except Exception as e:
            await update.message.reply_text(f"Could not switch character: {e}")
            return
        msg = f"Now operating as: {prof.get('name', cid)}"
        if prof.get("disclaimer"):
            msg += f"\n\n{prof['disclaimer']}"
        await update.message.reply_text(msg)

    async def graph_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        denied = self._capability_denied("memory")
        if denied:
            await update.message.reply_text(denied)
            return
        query = " ".join(context.args)
        if not query:
            await update.message.reply_text("Usage: /graph <query>")
            return
        try:
            res = await asyncio.to_thread(self.engine.graph_search, query, 15)
        except Exception as e:
            await update.message.reply_text(f"Graph error: {e}")
            return
        ents = res.get("entities", [])
        if not ents:
            await update.message.reply_text("No matching knowledge.")
            return
        lines = [f"Knowledge graph results for '{query}':"]
        for e in ents[:15]:
            lines.append(f"- {e['name']} [{e['kind']}] id={e['id']}")
            for r in e.get("relations", [])[:5]:
                lines.append(f"    {e['name']} {r['predicate']} {r['target']}")
        await update.message.reply_text("\n".join(lines)[:3800])

    async def graphstats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        denied = self._capability_denied("memory")
        if denied:
            await update.message.reply_text(denied)
            return
        try:
            s = await asyncio.to_thread(self.engine.graph_stats)
        except Exception as e:
            await update.message.reply_text(f"Graph error: {e}")
            return
        await update.message.reply_text(
            f"Knowledge graph\nEntities: {s.get('entities', 0)}\n"
            f"Relations: {s.get('relations', 0)}\nMemories: {s.get('memories', 0)}\n"
            f"Vector index: {s.get('vector')}\nDB: {s.get('db_path', '')}"
        )

    async def graphdel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        denied = self._capability_denied("memory")
        if denied:
            await update.message.reply_text(denied)
            return
        if not context.args:
            await update.message.reply_text("Usage: /graphdel <entity_id>")
            return
        eid = context.args[0].strip()
        try:
            ok = await asyncio.to_thread(self.engine.graph_delete_entity, eid)
        except Exception as e:
            await update.message.reply_text(f"Delete failed: {e}")
            return
        await update.message.reply_text("Entity deleted." if ok else "Entity not found.")

    async def pending_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        denied = self._capability_denied("memory")
        if denied:
            await update.message.reply_text(denied)
            return
        items = await asyncio.to_thread(self.engine.list_pending_graph)
        if not items:
            await update.message.reply_text("No pending knowledge.")
            return
        for item in items[:5]:
            p = item.get("payload", {})
            keyboard = [[
                InlineKeyboardButton("Approve", callback_data=f"gapprove_{item['id']}"),
                InlineKeyboardButton("Reject", callback_data=f"greject_{item['id']}"),
            ]]
            names = "\n".join(f"- {e['name']} [{e['kind']}]" for e in p.get("entities", [])[:8])
            text = (f"[{item.get('source','chat')}] {len(p.get('entities',[]))} entities, "
                    f"{len(p.get('relations',[]))} relations\n{names}")
            await update.message.reply_text(text[:3500], reply_markup=InlineKeyboardMarkup(keyboard))

    async def prompt_graph_approval(self, pid: str, proposal: dict):
        """Notify known chats that new knowledge needs approval."""
        if not self._chat_ids or not self.app:
            return
        keyboard = [[
            InlineKeyboardButton("Approve", callback_data=f"gapprove_{pid}"),
            InlineKeyboardButton("Reject", callback_data=f"greject_{pid}"),
        ]]
        names = "\n".join(f"- {e['name']} [{e['kind']}]" for e in proposal.get("entities", [])[:8])
        text = (f"New knowledge awaiting approval "
                f"({len(proposal.get('entities',[]))} entities, "
                f"{len(proposal.get('relations',[]))} relations):\n{names}\n\n"
                "Use /pending to review.")
        for chat_id in list(self._chat_ids):
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id, text=text[:3500],
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            except Exception as e:
                logger.error("Failed to send graph approval: %s", e)

    async def prompt_collab_request(self, req):
        """Notify known chats of an incoming collaboration request."""
        if not self._chat_ids or not self.app:
            return
        keyboard = [[
            InlineKeyboardButton("Accept", callback_data=f"caccept_{req.id}"),
            InlineKeyboardButton("Reject", callback_data=f"creject_{req.id}"),
        ]]
        text = (f"Incoming collaboration request from "
                f"{req.label or req.remote_fp[:12]}\n"
                f"Fingerprint: {req.remote_fp[:32]}...\n"
                f"Safety code (SAS): {req.sas}\n"
                "Verify the SAS with your peer before accepting.")
        for chat_id in list(self._chat_ids):
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id, text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as e:
                logger.error("Failed to send collab prompt: %s", e)

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
            "/setllm <id> - switch LLM\n"
            "/character - show/switch agent character\n"
            "/setcharacter <id> - activate a character\n"
            "/graph <query> - search the knowledge graph\n"
            "/pending - review proposed knowledge\n"
            "/graphdel <id> - delete a graph entity\n"
            "/whoami - show your Telegram user ID"
        )

    async def chat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        prompt = " ".join(context.args)
        if not prompt:
            await update.message.reply_text("Usage: /chat <message>")
            return
        try:
            reply = await asyncio.to_thread(self.engine.chat, prompt)
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"LLM error: {e}")

    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        denied = self._capability_denied("web_search")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("learn_web")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("download_media")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("skills_run")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("skills_manage")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("email_read")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("email_send")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("peripherals")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("peripherals")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("peripherals")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("peripherals")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("peripherals")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("memory")
        if denied:
            await update.message.reply_text(denied)
            return
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
        denied = self._capability_denied("memory")
        if denied:
            await update.message.reply_text(denied)
            return
        memories = self.engine.list_memories()
        if not memories:
            await update.message.reply_text("No retained data.")
            return
        lines = ["Retained data:"]
        for mem_id, content, created in memories[:10]:
            lines.append(f"- {content[:200]}")
        await update.message.reply_text("\n".join(lines)[:3800])

    async def predict_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        denied = self._capability_denied("predict")
        if denied:
            await update.message.reply_text(denied)
            return
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

    async def usage_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            s = await asyncio.to_thread(self.engine.usage_summary, 30)
        except Exception as e:
            await update.message.reply_text(f"Usage error: {e}")
            return
        lines = [f"LLM usage (last {s.get('days', 30)} days)",
                 f"Calls: {s.get('total_calls', 0)}   Tokens: {s.get('total_tokens', 0)}"]
        for p in s.get("by_provider", [])[:10]:
            lines.append(f"- {p['provider']}: {p['calls']} calls, "
                         f"{p['prompt_tokens'] + p['completion_tokens']} tokens")
        await update.message.reply_text("\n".join(lines)[:3800])

    async def notify_task(self, name, result):
        if not self._chat_ids or not self.app:
            return
        for chat_id in list(self._chat_ids):
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id, text=f"[scheduled task: {name}]\n{str(result)[:3500]}")
            except Exception:
                pass

    async def tasks_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tasks = await asyncio.to_thread(self.engine.list_scheduled_tasks)
        if not tasks:
            await update.message.reply_text("No scheduled tasks.")
            return
        lines = ["Scheduled tasks:"]
        for t in tasks:
            _tid, name, kind, payload, interval, _next, _enabled, _last_run, last_result = t
            lines.append(f"- {name} [{kind}] every {interval}s | last: {(last_result or '')[:120]}")
        await update.message.reply_text("\n".join(lines)[:3800])

    async def task_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        raw = " ".join(context.args)
        if "|" not in raw:
            await update.message.reply_text("Usage: /task <name> <minutes> | <prompt>")
            return
        head, prompt = raw.split("|", 1)
        parts = head.split()
        if len(parts) < 2:
            await update.message.reply_text("Usage: /task <name> <minutes> | <prompt>")
            return
        name = parts[0]
        try:
            secs = max(10, int(parts[1]) * 60)
        except ValueError:
            await update.message.reply_text("Minutes must be a whole number.")
            return
        await asyncio.to_thread(self.engine.add_scheduled_task, name, "ask", prompt.strip(), secs)
        await update.message.reply_text(f"Scheduled task '{name}' every {parts[1]} min.")

    async def deltask_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /deltask <name>")
            return
        n = await asyncio.to_thread(self.engine.delete_scheduled_task, context.args[0])
        await update.message.reply_text(f"Deleted {n} task(s).")

    async def plans_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        plans = await asyncio.to_thread(self.engine.plan_list, 20)
        if not plans:
            await update.message.reply_text("No plans.")
            return
        lines = ["Plans:"] + [f"- {p[0]}  {p[1][:60]}  [{p[2]}]" for p in plans]
        await update.message.reply_text("\n".join(lines)[:3800])

    async def newplan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        goal = " ".join(context.args)
        if not goal:
            await update.message.reply_text("Usage: /newplan <goal>")
            return
        pid = await asyncio.to_thread(self.engine.plan_create, goal, [])
        await update.message.reply_text(f"Plan created: {pid}")

    async def plan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /plan <plan_id>")
            return
        p = await asyncio.to_thread(self.engine.plan_get, context.args[0])
        if not p:
            await update.message.reply_text("Plan not found.")
            return
        lines = [f"{p['goal']} [{p['status']}]"]
        for s in p["steps"]:
            lines.append(f"{s['idx']}. [{s['status']}] {s['title']}")
        await update.message.reply_text("\n".join(lines)[:3800])

    async def image_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        prompt = " ".join(context.args)
        if not prompt:
            await update.message.reply_text("Usage: /image <prompt>")
            return
        await update.message.reply_text("Generating image...")
        try:
            path = await asyncio.to_thread(self.engine.generate_image, prompt)
        except Exception as e:
            await update.message.reply_text(f"Image error: {e}")
            return
        await update.message.reply_text(f"Image saved: {path}")

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

        if data.startswith("gapprove_"):
            pid = data[len("gapprove_"):]
            ok = await asyncio.to_thread(self.engine.approve_pending_graph, pid)
            await query.edit_message_text(
                text="Approved and stored in the knowledge graph." if ok else "Approval failed.")
            return
        if data.startswith("greject_"):
            pid = data[len("greject_"):]
            await asyncio.to_thread(self.engine.reject_pending_graph, pid)
            await query.edit_message_text(text="Rejected.")
            return
        if data.startswith("caccept_") or data.startswith("creject_"):
            accept = data.startswith("caccept_")
            req_id = data.split("_", 1)[1]
            await asyncio.to_thread(self.engine.resolve_collab, req_id, accept)
            await query.edit_message_text(text="Accepted." if accept else "Rejected.")
            return

        if data in ("dl_mp3", "dl_mp4"):
            denied = self._capability_denied("download_media")
            if denied:
                await query.edit_message_text(text=denied)
                return
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
            denied = self._capability_denied("skills_manage")
            if denied:
                await query.edit_message_text(text=denied)
                return
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
