// SPDX-License-Identifier: GPL-3.0-or-later
// Remote-control client: crypto vector shared with tests/test_remote_api.py, pairing links, a fake
// sealed server (MockWebServer), and an interop test against the real desktop server when available.
package org.kairos.agent

import kotlinx.serialization.json.*
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.kairos.agent.remote.*
import java.io.File
import java.util.concurrent.TimeUnit

class RemoteTest {
    private val secret = RemoteCrypto.b64e(ByteArray(32) { it.toByte() })

    @Test fun knownVectorMatchesDesktop() {
        val key = RemoteCrypto.deriveKey(secret)
        assertEquals("aa40b0756d7874a5acadca61b8b409985915c707bc7b06f7cbb6c5b4f90d228f", key.joinToString("") { "%02x".format(it) })
        assertEquals("aa609800", RemoteCrypto.keyId(key))
        val (_, c) = RemoteCrypto.seal(key, """{"op":"ping"}""".toByteArray(), RemoteCrypto.reqAad(1700000000), ByteArray(12))
        assertEquals("ofjvu6mWWm60OkaarF_gsoc2glyksuVUeRLhyWI", RemoteCrypto.b64e(c))
        assertEquals("""{"op":"ping"}""", String(RemoteCrypto.open(key, ByteArray(12), c, RemoteCrypto.reqAad(1700000000))))
        assertThrows(Exception::class.java) { RemoteCrypto.open(key, ByteArray(12), c, RemoteCrypto.reqAad(1700000001)) }
    }

    @Test fun pairingLinks() {
        val p = PairingLink.parse("kairos://pair?host=192.168.1.5&port=8766&key=$secret&name=My%20PC")
        assertEquals(Pairing("192.168.1.5", 8766, secret, "My PC"), p)
        for (bad in listOf("https://x", "kairos://pair?host=1.2.3.4&port=0&key=$secret", "kairos://pair?host=a b&port=1&key=$secret",
                "kairos://pair?host=1.2.3.4&port=80&key=short"))
            assertThrows(IllegalArgumentException::class.java) { PairingLink.parse(bad) }
    }

    /** Minimal server implementing the desktop protocol, for client behaviour tests. */
    private fun fakeServer(): MockWebServer = MockWebServer().apply {
        val key = RemoteCrypto.deriveKey(secret)
        val jobs = mutableMapOf<String, Int>()
        dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val env = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                if (env["kid"]!!.jsonPrimitive.content != RemoteCrypto.keyId(key)) return MockResponse().setResponseCode(401).setBody("""{"error":"unauthorized"}""")
                val n = env["n"]!!.jsonPrimitive.content
                val req = Json.parseToJsonElement(String(RemoteCrypto.open(key, RemoteCrypto.b64d(n), RemoteCrypto.b64d(env["c"]!!.jsonPrimitive.content),
                    RemoteCrypto.reqAad(env["ts"]!!.jsonPrimitive.long)))).jsonObject
                val args = req["args"]!!.jsonObject
                val result: JsonObject = when (req["op"]!!.jsonPrimitive.content) {
                    "ping" -> buildJsonObject { put("ok", true); putJsonObject("result") { put("name", "PC"); put("version", "0.16.5"); put("character", "General") } }
                    "chat" -> buildJsonObject { put("ok", true); put("result", "echo: " + args["prompt"]!!.jsonPrimitive.content) }
                    "submit" -> { jobs["job-1"] = 0; buildJsonObject { put("ok", true); putJsonObject("result") { put("id", "job-1") } } }
                    "job" -> { val k = jobs.merge("job-1", 1, Int::plus)!!
                        buildJsonObject { put("ok", true); putJsonObject("result") { put("id", "job-1"); put("prompt", "x"); put("mode", "execute")
                            put("status", if (k >= 2) "done" else "running"); put("progress", "step"); put("result", "finished") } } }
                    "jobs" -> buildJsonObject { put("ok", true); putJsonArray("result") { addJsonObject { put("id", "job-1"); put("status", "done") } } }
                    else -> buildJsonObject { put("ok", false); put("error", "unknown op") }
                }
                val (rn, rc) = RemoteCrypto.seal(key, result.toString().toByteArray(), RemoteCrypto.respAad(n))
                return MockResponse().setBody(buildJsonObject { put("v", 1); put("n", RemoteCrypto.b64e(rn)); put("c", RemoteCrypto.b64e(rc)) }.toString())
            }
        }
        start()
    }

    @Test fun clientAgainstFakeServer() {
        val s = fakeServer()
        try {
            val c = RemoteClient(Pairing(s.hostName, s.port, secret, "PC"))
            assertEquals("PC · Kairos 0.16.5 · General", c.ping())
            assertEquals("echo: hi", c.chat("hi"))
            val updates = mutableListOf<String>()
            val j = c.runJob("x", "execute", pollMs = 1) { updates += it.status }
            assertEquals("done", j.status); assertEquals("finished", j.result); assertEquals(listOf("running", "done"), updates)
            assertEquals(1, c.jobs().size)
            assertEquals("unknown op", assertThrows(RemoteError::class.java) { c.call("bogus") }.message)
            val wrong = RemoteClient(Pairing(s.hostName, s.port, RemoteCrypto.b64e(ByteArray(32) { 9 }), "PC"))
            assertTrue(assertThrows(RemoteError::class.java) { wrong.ping() }.message!!.contains("rejected"))
        } finally { s.shutdown() }
    }

    /** Runs the real desktop server (kairos/remote_api.py serve-test) when Python + cryptography exist. */
    @Test fun interopWithDesktopServer() {
        val repo = File("../..").canonicalFile
        assumeTrue(File(repo, "kairos/remote_api.py").isFile)
        val py = System.getenv("KAIROS_PYTHON") ?: "python3"
        assumeTrue(runCatching { ProcessBuilder(py, "-c", "import cryptography").start().waitFor() == 0 }.getOrDefault(false))
        val port = java.net.ServerSocket(0).use { it.localPort }
        val proc = ProcessBuilder(py, "-m", "kairos.remote_api", "serve-test", "--host", "127.0.0.1", "--port", "$port", "--secret", secret)
            .directory(repo).redirectErrorStream(true).start()
        try {
            val line = proc.inputStream.bufferedReader().readLine()
            assertTrue("server output: $line", line?.contains("test server") == true)
            val c = RemoteClient(Pairing("127.0.0.1", port, secret, "PC"))
            assertTrue(c.ping().contains("0.16.5"))
            assertEquals("echo: hello", c.chat("hello"))
            val j = c.runJob("build the report", "execute", pollMs = 100)
            assertEquals("done", j.status)
            assertEquals("done [execute]: build the report", j.result)
            assertEquals("step 1/1", j.progress)
        } finally { proc.destroy(); proc.waitFor(5, TimeUnit.SECONDS) }
    }
}
