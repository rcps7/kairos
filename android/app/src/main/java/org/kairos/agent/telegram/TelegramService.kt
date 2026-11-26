// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Runs the Telegram bot's long polling in a user-toggled
// foreground service so the bot keeps answering while the app is in the background.
package org.kairos.agent.telegram

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import kotlinx.coroutines.*
import org.kairos.agent.KairosApp
import org.kairos.agent.data.SecureStore

class TelegramService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var poll: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Telegram bot", NotificationManager.IMPORTANCE_LOW))
        val n = Notification.Builder(this, CHANNEL).setContentTitle("KAIROS Telegram bot")
            .setContentText("Listening for commands").setSmallIcon(android.R.drawable.stat_notify_chat).setOngoing(true).build()
        startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        if (poll?.isActive != true) {
            val app = application as KairosApp
            val token = app.secrets.get(SecureStore.TELEGRAM_TOKEN).orEmpty().trim()
            if (!validateTokenFormat(token)) {
                status = "Telegram token format looks wrong (expected '<digits>:<secret>')."
                stopSelf(); return START_NOT_STICKY
            }
            val bot = TelegramBot(TelegramApi(token), app.botHost)
            current = bot
            status = "Starting…"
            poll = scope.launch {
                status = try { "Connected as @${TelegramApi(token).getMe()}" } catch (e: Exception) { e.message ?: "Telegram error" }
                bot.run()
                status = bot.lastError ?: "Stopped"
                stopSelf()
            }
        }
        return START_STICKY
    }

    override fun onDestroy() { scope.cancel(); current = null; super.onDestroy() }

    companion object {
        private const val CHANNEL = "kairos_telegram"
        private const val ID = 7002
        @Volatile var status: String = "Off"
        @Volatile var current: TelegramBot? = null

        fun start(ctx: Context) = ctx.startForegroundService(Intent(ctx, TelegramService::class.java))
        fun stop(ctx: Context) { ctx.stopService(Intent(ctx, TelegramService::class.java)); status = "Off" }
    }
}
