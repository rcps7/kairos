// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Keeps queued agent jobs alive while the app is in the background
// (FEASIBILITY: "long jobs promoted to a foreground service"). Runs only while the job queue is non-empty.
package org.kairos.agent

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import org.kairos.agent.jobs.JobQueue

class KairosJobService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Background jobs", NotificationManager.IMPORTANCE_LOW))
        val n = Notification.Builder(this, CHANNEL)
            .setContentTitle("KAIROS is working")
            .setContentText("Running queued agent jobs")
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true).build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else startForeground(ID, n)
        // The service stops itself once the queue drains. Callers never call stopService() directly:
        // stopping before onStartCommand reaches startForeground() crashes the app on Android 10+.
        if (watcher == null) {
            val jobs = (application as KairosApp).jobs
            watcher = scope.launch {
                jobs.pendingFlow.first { it == 0 }
                stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); watcher = null
            }
        }
        return START_NOT_STICKY
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var watcher: kotlinx.coroutines.Job? = null

    override fun onDestroy() { scope.cancel(); super.onDestroy() }

    companion object {
        private const val CHANNEL = "kairos_jobs"
        private const val ID = 7001

        /** Start the service when the queue gets work and stop it when it drains. */
        fun observe(ctx: Context, jobs: JobQueue) {
            CoroutineScope(SupervisorJob() + Dispatchers.Main).launch {
                jobs.pendingFlow.map { it > 0 }.distinctUntilChanged().collect { busy ->
                    val i = Intent(ctx, KairosJobService::class.java)
                    if (!busy) return@collect
                    try {
                        ctx.startForegroundService(i)
                    } catch (_: Exception) {
                        // Background-start restrictions: jobs still run in-process while the app is visible.
                    }
                }
            }
        }
    }
}
