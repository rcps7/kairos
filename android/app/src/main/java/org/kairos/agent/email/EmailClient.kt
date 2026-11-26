// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Port of kairos/email_client.py (IMAP read, SMTP send).
// Uses Jakarta Mail for Android (com.sun.mail:android-mail, EPL-2.0 OR GPL-2.0-with-Classpath-exception).
// Only acts on explicit user request.
package org.kairos.agent.email

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.Date
import java.util.Properties
import javax.mail.Folder
import javax.mail.Message
import javax.mail.Multipart
import javax.mail.Part
import javax.mail.Session
import javax.mail.internet.InternetAddress
import javax.mail.internet.MimeMessage

data class EmailConfig(
    val email: String = "",
    val password: String = "",
    val imapHost: String = "",
    val imapPort: Int = 993,
    val smtpHost: String = "",
    val smtpPort: Int = 465,
    /** Desktop always uses IMAP4_SSL / SMTP_SSL; plain sockets exist only for local tests. */
    val ssl: Boolean = true,
)

data class MailItem(val from: String, val subject: String, val date: String, val body: String)

class EmailNotConfigured : RuntimeException("Email is not configured. Add email settings in the Connect tab.")

class EmailClient(private val config: () -> EmailConfig) {

    private fun require(c: EmailConfig) {
        if (c.imapHost.isBlank() || c.email.isBlank()) throw EmailNotConfigured()
    }

    private fun session(c: EmailConfig): Session {
        val p = Properties()
        val imap = if (c.ssl) "imaps" else "imap"
        val smtp = if (c.ssl) "smtps" else "smtp"
        p["mail.store.protocol"] = imap
        p["mail.$imap.host"] = c.imapHost; p["mail.$imap.port"] = c.imapPort.toString()
        p["mail.$imap.connectiontimeout"] = "20000"; p["mail.$imap.timeout"] = "30000"
        p["mail.$smtp.host"] = c.smtpHost; p["mail.$smtp.port"] = c.smtpPort.toString()
        p["mail.$smtp.auth"] = "true"
        p["mail.$smtp.connectiontimeout"] = "20000"; p["mail.$smtp.timeout"] = "30000"
        if (c.ssl) { p["mail.imaps.ssl.checkserveridentity"] = "true"; p["mail.smtps.ssl.checkserveridentity"] = "true" }
        return Session.getInstance(p)
    }

    /** Latest [limit] messages from INBOX, newest first (desktop read_mail). */
    suspend fun readMail(limit: Int = 10): List<MailItem> = withContext(Dispatchers.IO) {
        val c = config(); require(c)
        val store = session(c).getStore(if (c.ssl) "imaps" else "imap")
        store.connect(c.imapHost, c.imapPort, c.email, c.password)
        try {
            val inbox = store.getFolder("INBOX"); inbox.open(Folder.READ_ONLY)
            try {
                val n = inbox.messageCount
                if (n == 0) return@withContext emptyList()
                inbox.getMessages(maxOf(1, n - limit + 1), n).reversed().map { m ->
                    MailItem(
                        from = m.from?.joinToString { it.toString() }.orEmpty(),
                        subject = m.subject.orEmpty(),
                        date = (m.sentDate ?: m.receivedDate)?.toString().orEmpty(),
                        body = textBody(m),
                    )
                }
            } finally { inbox.close(false) }
        } finally { store.close() }
    }

    suspend fun sendMail(to: String, subject: String, body: String): Boolean = withContext(Dispatchers.IO) {
        val c = config(); require(c)
        if (c.smtpHost.isBlank()) throw EmailNotConfigured()
        val s = session(c)
        val msg = MimeMessage(s).apply {
            setFrom(InternetAddress(c.email))
            setRecipients(Message.RecipientType.TO, InternetAddress.parse(to, true))
            setSubject(subject, "UTF-8")
            sentDate = Date()
            setText(body, "UTF-8")
        }
        val t = s.getTransport(if (c.ssl) "smtps" else "smtp")
        t.connect(c.smtpHost, c.smtpPort, c.email, c.password)
        try { t.sendMessage(msg, msg.allRecipients) } finally { t.close() }
        true
    }

    companion object {
        /** First text/plain part (desktop extract_text_body); falls back to stripped HTML. */
        fun textBody(p: Part): String {
            if (p.isMimeType("text/plain")) return p.content?.toString().orEmpty()
            if (p.isMimeType("multipart/*")) {
                val mp = p.content as Multipart
                for (i in 0 until mp.count) {
                    val t = textBody(mp.getBodyPart(i)); if (t.isNotEmpty() && !mp.getBodyPart(i).isMimeType("text/html")) return t
                }
                for (i in 0 until mp.count) { val t = textBody(mp.getBodyPart(i)); if (t.isNotEmpty()) return t }
                return ""
            }
            if (p.isMimeType("text/html")) return org.jsoup.Jsoup.parse(p.content?.toString().orEmpty()).text()
            return ""
        }

        fun format(items: List<MailItem>, bodyChars: Int = 200): String =
            if (items.isEmpty()) "No email." else
                (listOf("Latest emails:") + items.map { "From: ${it.from}\nSubject: ${it.subject}\n${it.body.trim().take(bodyChars)}" })
                    .joinToString("\n\n")
    }
}
