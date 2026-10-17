package de.dodaios.mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import kotlin.random.Random

/**
 * Keeps one long-poll open to the PC so Jarvis can ring this phone. There is no
 * push service: while this foreground service runs, a ring arrives within seconds.
 */
class RingService : Service() {
    @Volatile private var running = false
    private var worker: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannels(this)
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(this, WATCH_CHANNEL)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.watch_text))
            .setContentIntent(open)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(WATCH_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING)
        } else {
            startForeground(WATCH_ID, notification)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!running) {
            running = true
            worker = Thread(::poll, "ring-poll").also { it.start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        worker?.interrupt()
        worker = null
        super.onDestroy()
    }

    private fun poll() {
        while (running) {
            val pairing = SecureStore(this).load()
            if (pairing == null) {
                stopSelf()
                return
            }
            try {
                val ring = GatewayClient(pairing.host, pairing.port, pairing.fingerprint).ring(pairing.token)
                if (ring != null) showIncoming(this, ring.optString("text"))
            } catch (e: GatewayException) {
                if (e.message == "Gerät nicht (mehr) gekoppelt") {
                    stopSelf()
                    return
                }
                pause()
            } catch (_: Exception) {
                pause() // PC offline or network change; try again shortly
            }
        }
    }

    private fun pause() {
        try {
            Thread.sleep(10_000L + Random.nextLong(10_000L))
        } catch (_: InterruptedException) {
            running = false
        }
    }

    companion object {
        const val RING_CHANNEL = "jarvis_ring"
        const val WATCH_CHANNEL = "jarvis_watch"
        const val RING_ID = 2
        const val WATCH_ID = 1
        const val EXTRA_TEXT = "text"

        fun start(context: Context) {
            ContextCompat.startForegroundService(context, Intent(context, RingService::class.java))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, RingService::class.java))
        }

        fun cancelIncoming(context: Context) {
            context.getSystemService(NotificationManager::class.java).cancel(RING_ID)
        }

        private fun showIncoming(context: Context, text: String) {
            val screen = Intent(context, IncomingCallActivity::class.java)
                .putExtra(EXTRA_TEXT, text)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            val full = PendingIntent.getActivity(
                context, 1, screen, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            val notification = NotificationCompat.Builder(context, RING_CHANNEL)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(context.getString(R.string.incoming))
                .setContentText(text)
                .setCategory(NotificationCompat.CATEGORY_CALL)
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setContentIntent(full)
                .setFullScreenIntent(full, true)
                .setAutoCancel(true)
                .setTimeoutAfter(60_000L)
                .build()
            notification.flags = notification.flags or Notification.FLAG_INSISTENT
            context.getSystemService(NotificationManager::class.java).notify(RING_ID, notification)
        }

        private fun createChannels(context: Context) {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(
                    WATCH_CHANNEL, context.getString(R.string.watch_channel), NotificationManager.IMPORTANCE_MIN,
                ),
            )
            manager.createNotificationChannel(
                NotificationChannel(
                    RING_CHANNEL, context.getString(R.string.ring_channel), NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    setSound(
                        RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE),
                        AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE).build(),
                    )
                    enableVibration(true)
                    vibrationPattern = longArrayOf(0, 800, 600, 800, 600)
                },
            )
        }
    }
}
