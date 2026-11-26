// SPDX-License-Identifier: GPL-3.0-or-later
// Email read/send (desktop kairos/email_client.py) against an in-process GreenMail IMAP/SMTP server.
package org.kairos.agent

import com.icegreen.greenmail.util.GreenMail
import com.icegreen.greenmail.util.ServerSetup
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.kairos.agent.agent.*
import org.kairos.agent.email.EmailClient
import org.kairos.agent.email.EmailConfig
import org.kairos.agent.email.EmailNotConfigured
import java.io.File
import java.net.ServerSocket
import java.util.Properties
import javax.mail.Session
import javax.mail.internet.MimeBodyPart
import javax.mail.internet.MimeMessage
import javax.mail.internet.MimeMultipart

class EmailTest {
    private lateinit var gm: GreenMail
    private lateinit var cfg: EmailConfig

    private fun freePort() = ServerSocket(0).use { it.localPort }

    @Before fun up() {
        val smtp = ServerSetup(freePort(), "127.0.0.1", ServerSetup.PROTOCOL_SMTP)
        val imap = ServerSetup(freePort(), "127.0.0.1", ServerSetup.PROTOCOL_IMAP)
        gm = GreenMail(arrayOf(smtp, imap)); gm.start()
        gm.setUser("rc@kairos.test", "rc@kairos.test", "secret")
        cfg = EmailConfig("rc@kairos.test", "secret", "127.0.0.1", imap.port, "127.0.0.1", smtp.port, ssl = false)
    }

    @After fun down() { gm.stop() }

    @Test fun sendThenReadNewestFirst() = runBlocking {
        val c = EmailClient { cfg }
        assertTrue(c.sendMail("rc@kairos.test", "First", "hello one"))
        assertTrue(c.sendMail("rc@kairos.test", "Second ✓", "hello two — unicode"))
        assertTrue(gm.waitForIncomingEmail(5000, 2))
        val got = c.readMail(10)
        assertEquals(listOf("Second ✓", "First"), got.map { it.subject })
        assertTrue(got[0].body.contains("hello two — unicode"))
        assertTrue(got[0].from.contains("rc@kairos.test"))
        assertEquals(1, c.readMail(1).size)
    }

    @Test fun multipartPrefersPlainText() {
        val m = MimeMessage(Session.getInstance(Properties()))
        val mp = MimeMultipart("alternative")
        mp.addBodyPart(MimeBodyPart().apply { setContent("<p>HTML <b>body</b></p>", "text/html; charset=utf-8") })
        mp.addBodyPart(MimeBodyPart().apply { setText("plain body", "utf-8") })
        m.setContent(mp); m.saveChanges()
        assertEquals("plain body", EmailClient.textBody(m))
        val h = MimeMessage(Session.getInstance(Properties())).apply { setContent("<p>Only <b>html</b></p>", "text/html; charset=utf-8"); saveChanges() }
        assertEquals("Only html", EmailClient.textBody(h))
    }

    @Test fun notConfiguredIsReported() = runBlocking {
        val e = runCatching { EmailClient { EmailConfig() }.readMail() }.exceptionOrNull()
        assertTrue(e is EmailNotConfigured)
    }

    @Test fun emailToolsRespectCapabilities() = runBlocking {
        val pack = CharacterRegistry.parsePack(File("src/main/assets/characters.json").readText())
        val reg = CharacterRegistry(pack, listOf(pack.presets[0].copy(id = "reader", capabilities = listOf("email_read"))))
        reg.activeId = "reader"
        val t = EmailTools(reg, EmailClient { cfg })
        assertEquals("(tool not permitted: email_send)", t.run(ToolCall("send_email", mapOf("to" to "x@y", "subject" to "s", "body" to "b"))))
        EmailClient { cfg }.sendMail("rc@kairos.test", "Tool test", "via tool")
        assertTrue(gm.waitForIncomingEmail(5000, 1))
        assertTrue(t.run(ToolCall("read_email", mapOf("limit" to "3"))).contains("Subject: Tool test"))
        // Advanced <tool> protocol reaches the email tools.
        val (_, calls) = Tools.parse("<tool name=\"read_email\">{\"limit\": 1}</tool>")
        assertTrue(t.run(calls[0]).contains("Tool test"))
    }
}
