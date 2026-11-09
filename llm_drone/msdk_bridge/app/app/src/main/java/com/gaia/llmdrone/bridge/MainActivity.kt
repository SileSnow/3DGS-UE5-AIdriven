package com.gaia.llmdrone.bridge

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.gaia.llmdrone.bridge.bridge.BridgeService
import com.gaia.llmdrone.bridge.msdk.MsdkInitManager

/**
 * 极简调试界面：显示 MSDK 注册/连接状态与 HTTP 端口，并把 App 拉起到前台以保持进程。
 * 真正的业务接口全部走本机 HTTP（DroneBridgeServer），真机测试时由 adb forward 暴露给 Orchestrator。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var statusView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        statusView = TextView(this).apply {
            textSize = 14f
            setPadding(48, 96, 48, 48)
        }
        setContentView(statusView)
        requestRuntimePermissions()
        startBridgeService()

        // 每 1s 刷新一次状态（骨架级 UI，不做复杂绑定）
        statusView.postDelayed(object : Runnable {
            override fun run() {
                statusView.text = buildStatusText()
                statusView.postDelayed(this, 1000)
            }
        }, 500)
    }

    private fun buildStatusText(): String = buildString {
        appendLine("LLM Drone MSDK Bridge v0.1.0")
        appendLine("MSDK registered: " + MsdkInitManager.isRegistered)
        appendLine("product connected: " + MsdkInitManager.isProductConnected)
        appendLine("aircraft model: " + MsdkInitManager.aircraftModel)
        appendLine("bridge port: " + BridgeService.PORT)
        appendLine("---")
        appendLine("本机无真机/SDK：此界面仅用于说明运行期状态。")
        appendLine("详见 llm_drone/msdk_bridge/README.md 的\"未执行边界\"。")
    }

    private fun requestRuntimePermissions() {
        val perms = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= 33) perms += Manifest.permission.POST_NOTIFICATIONS
        if (Build.VERSION.SDK_INT <= 32) perms += Manifest.permission.READ_EXTERNAL_STORAGE
        val missing = perms.filter { ContextCompat.checkSelfPermission(this, it) != android.content.pm.PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, missing.toTypedArray(), 1001)
        }
    }

    private fun startBridgeService() {
        val i = Intent(this, BridgeService::class.java)
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(i) else startService(i)
    }
}
