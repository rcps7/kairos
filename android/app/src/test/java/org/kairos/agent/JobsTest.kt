// SPDX-License-Identifier: GPL-3.0-or-later
// Ported from tests/test_jobs.py (FIFO job queue).
package org.kairos.agent

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.jobs.Job
import org.kairos.agent.jobs.JobQueue
import java.util.Collections
import java.util.concurrent.atomic.AtomicInteger

class JobsTest {
    @Test fun fifoOrderAndSerialization() = runBlocking {
        val q = JobQueue()
        val events = Collections.synchronizedList(mutableListOf<Any?>())
        val active = AtomicInteger(0); val maxActive = AtomicInteger(0)
        for (i in 0 until 5) q.submit(Job(label = "j$i", onDone = { _, r -> events += r }) { chunk, _ ->
            maxActive.accumulateAndGet(active.incrementAndGet(), ::maxOf)
            delay(20); chunk("c$i"); active.decrementAndGet(); i
        })
        assertTrue(q.waitIdle(5000))
        assertEquals(listOf(0, 1, 2, 3, 4), events)
        assertEquals(1, maxActive.get())
    }

    @Test fun chunksAndProgressAreRoutedWithJobId() = runBlocking {
        val q = JobQueue()
        val chunks = Collections.synchronizedMap(mutableMapOf<String, MutableList<String>>())
        val progress = Collections.synchronizedList(mutableListOf<String>())
        val id = q.submit(Job(label = "x",
            onChunk = { jid, t -> chunks.getOrPut(jid) { mutableListOf() } += t },
            onProgress = { _, t -> progress += t }) { chunk, prog -> prog("working"); chunk("a"); chunk("b"); "ok" })
        assertTrue(q.waitIdle(5000))
        assertEquals(mapOf(id to listOf("a", "b")), chunks.toMap())
        assertEquals(listOf("working"), progress.toList())
    }

    @Test fun errorDoesNotBlockTheQueue() = runBlocking {
        val q = JobQueue()
        val done = Collections.synchronizedList(mutableListOf<Pair<String, String>>())
        q.submit(Job(label = "bad", onError = { _, e -> done += "err" to (e.message ?: "") }) { _, _ -> throw IllegalStateException("boom") })
        q.submit(Job(label = "good", onDone = { _, r -> done += "ok" to (r as String) }) { _, _ -> "ok" })
        assertTrue(q.waitIdle(5000))
        assertEquals("err", done[0].first); assertTrue(done[0].second.contains("boom"))
        assertEquals("ok" to "ok", done[1])
    }

    @Test fun pendingAndBusyCounts() = runBlocking {
        val q = JobQueue()
        val release = CompletableDeferred<Unit>()
        q.submit(Job(label = "block") { _, _ -> release.await() })
        repeat(200) { if (q.isBusy()) return@repeat; delay(5) }
        q.submit(Job(label = "queued") { _, _ -> null })
        assertEquals(2, q.pending())
        assertEquals(2, q.pendingFlow.value)
        release.complete(Unit)
        assertTrue(q.waitIdle(5000))
        assertEquals(0, q.pending())
    }
}
