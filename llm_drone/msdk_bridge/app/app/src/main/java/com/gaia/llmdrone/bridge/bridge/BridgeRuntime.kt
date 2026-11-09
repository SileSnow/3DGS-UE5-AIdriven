package com.gaia.llmdrone.bridge.bridge

import android.content.Context
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter

/**
 * 桥接层运行期单例状态（模式/状态机/当前任务）。
 * 状态枚举严格按 PROTOCOL.md §5：idle|taking_off|hovering|mission|returning|landing|aborted|failsafe
 */
object BridgeRuntime {

    const val BACKEND = "msdk"
    const val VERSION = "0.1.0"

    @Volatile lateinit var appContext: Context

    @Volatile var mode: String = "real"          // dry_run | real（sim 不支持）
    @Volatile var state: String = "idle"
    @Volatile var currentMissionId: String? = null
    @Volatile var missionActive: Boolean = false
    @Volatile var lastAbortReason: String? = null
    @Volatile var bridgeStartedAtMs: Long = System.currentTimeMillis()

    private val missionSeq = java.util.concurrent.atomic.AtomicInteger(0)

    fun nowIso(): String = OffsetDateTime.now().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)

    fun nextMissionId(): String = String.format("m-%04d", missionSeq.incrementAndGet())

    fun resetForMode(newMode: String) {
        mode = newMode
        state = "idle"
    }

    fun setState(newState: String) {
        if (state != newState) {
            state = newState
        }
    }

    fun elapsedRealSeconds(): Double =
        (System.currentTimeMillis() - bridgeStartedAtMs) / 1000.0
}
