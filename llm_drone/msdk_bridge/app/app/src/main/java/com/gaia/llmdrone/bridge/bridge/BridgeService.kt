package com.gaia.llmdrone.bridge.bridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import com.gaia.llmdrone.bridge.media.MediaDownloader
import com.gaia.llmdrone.bridge.msdk.AircraftConnectionManager
import com.gaia.llmdrone.bridge.gimbal.GimbalController

/**
 * 前台服务：承载 MSDK 监听 + HTTP server，避免 App 退后台被系统杀掉导致任务中断。
 * 官方依据：DJI 文档提示 App 在后台时部分功能受限；任务执行期间应保持前台（README "已知限制"）。
 */
class BridgeService : Service() {

    private var server: DroneBridgeServer? = null

    override fun onCreate() {
        super.onCreate()
        BridgeRuntime.appContext = applicationContext
        startForegroundCompat()
        MissionStore.init()
        AuditLogger.init(applicationContext, "default")
        MediaDownloader.init(applicationContext)
        AircraftConnectionManager.start(applicationContext)
        TelemetryPublisher.startListening(this)
        GimbalController.startListening(this)
        server = DroneBridgeServer(PORT).also {
            try {
                it.start(DroneBridgeServer.SOCKET_READ_TIMEOUT, true)
                Log.i(TAG, "bridge http server started on 0.0.0.0:" + PORT)
            } catch (t: Throwable) {
                Log.e(TAG, "start http server failed: " + t.message)
            }
        }
        AuditLogger.append("bridge_started", org.json.JSONObject().apply { put("port", PORT) })
    }

    override fun onDestroy() {
        try { server?.stop() } catch (t: Throwable) { Log.w(TAG, "stop server: " + t.message) }
        TelemetryPublisher.stopListening(this)
        AircraftConnectionManager.stop(this)
        AuditLogger.append("bridge_stopped", org.json.JSONObject())
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startForegroundCompat() {
        val channelId = "bridge_http"
        if (Build.VERSION.SDK_INT >= 26) {
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(
                NotificationChannel(channelId, "Bridge HTTP Server", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val builder = if (Build.VERSION.SDK_INT >= 26) {
            Notification.Builder(this, channelId)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        val notif = builder
            .setContentTitle("LLM Drone Bridge")
            .setContentText("MSDK bridge HTTP server on port " + PORT)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .build()
        startForeground(1001, notif)
    }

    companion object {
        private const val TAG = "BridgeService"
        // 端口固定 8765，与 spec 默认一致；如需改端口请同时改 gradle.properties 与 README
        const val PORT = 8765
    }
}
