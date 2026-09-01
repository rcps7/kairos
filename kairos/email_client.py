import imaplib
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate

from kairos import config

logger = logging.getLogger(__name__)


class EmailClient:
    """IMAP/SMTP email access. Only acts on explicit user request."""

    def __init__(self):
        self._config = config.load_config().get("email", {})

    def _require_config(self):
        if not self._config.get("imap_host") or not self._config.get("email"):
            raise RuntimeError(
                "Email is not configured. Add email settings via the GUI menu."
            )

    def read_mail(self, limit: int = 10) -> list:
        self._require_config()
        c = self._config
        messages = []
        with imaplib.IMAP4_SSL(c["imap_host"], int(c.get("imap_port", 993))) as M:
            M.login(c["email"], c["password"])
            M.select("INBOX")
            typ, data = M.search(None, "ALL")
            if typ != "OK" or not data[0]:
                return []
            ids = data[0].split()[-limit:]
            for num in reversed(ids):
                typ, msg_data = M.fetch(num, "(RFC822)")
                if typ != "OK":
                    continue
                raw = msg_data[0][1]
                msg = email_message_from_bytes(raw)
                messages.append({
                    "from": msg.get("From", ""),
                    "subject": msg.get("Subject", ""),
                    "date": msg.get("Date", ""),
                    "body": extract_text_body(msg),
                })
        return messages

    def send_mail(self, to: str, subject: str, body: str) -> bool:
        self._require_config()
        c = self._config
        msg = MIMEMultipart()
        msg["From"] = c["email"]
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP_SSL(c["smtp_host"], int(c.get("smtp_port", 465))) as S:
            S.login(c["email"], c["password"])
            S.sendmail(c["email"], [to], msg.as_string())
        return True


def email_message_from_bytes(raw: bytes):
    from email import message_from_bytes
    return message_from_bytes(raw)


def extract_text_body(msg) -> str:
    from email import policy
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_content()
    return msg.get_content()
