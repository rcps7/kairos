// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Port of kairos/jobs.py: a serial FIFO job queue.
// Jobs run strictly one at a time in submission order; the user can submit more work while one runs.
package org.kairos.agent.jobs

import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.concurrent.atomic.AtomicInteger

private val ids = AtomicInteger(0)

class Job(
    val label: String = "job",
    val id: String = "job-${ids.incrementAndGet()}",
    val onStart: ((String) -> Unit)? = null,
    val onChunk: ((String, String) -> Unit)? = null,
    val onProgress: ((String, String) -> Unit)? = null,
    val onDone: ((String, Any?) -> Unit)? = null,
    val onError: ((String, Throwable) -> Unit)? = null,
    val run: suspend (emitChunk: (String) -> Unit, emitProgress: (String) -> Unit) -> Any?,
) {
    fun emitChunk(text: String) { if (text.isNotEmpty()) onChunk?.invoke(id, text) }
    fun emitProgress(text: String) { if (text.isNotEmpty()) onProgress?.invoke(id, text) }
}

class JobQueue(scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)) {
    private val channel = Channel<Job>(Channel.UNLIMITED)
    private val count = AtomicInteger(0)
    private val _pending = MutableStateFlow(0)
    @Volatile private var current: Job? = null

    /** Number of jobs queued or running (observable, e.g. for the foreground service). */
    val pendingFlow: StateFlow<Int> = _pending

    init {
        scope.launch {
            for (job in channel) {
                current = job
                try {
                    job.onStart?.invoke(job.id)
                    val result = job.run(job::emitChunk, job::emitProgress)
                    job.onDone?.invoke(job.id, result)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Throwable) {
                    job.onError?.invoke(job.id, e)
                } finally {
                    current = null
                    _pending.value = count.decrementAndGet()
                }
            }
        }
    }

    fun submit(job: Job): String {
        _pending.value = count.incrementAndGet()
        channel.trySend(job)
        return job.id
    }

    fun isBusy(): Boolean = current != null
    fun pending(): Int = count.get()

    /** Suspend until the queue drains (tests). Returns false on timeout. */
    suspend fun waitIdle(timeoutMs: Long = 5000): Boolean =
        withTimeoutOrNull(timeoutMs) { while (count.get() > 0) delay(5); true } ?: false
}
