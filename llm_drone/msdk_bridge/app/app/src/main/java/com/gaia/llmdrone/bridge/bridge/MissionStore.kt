package com.gaia.llmdrone.bridge.bridge

import android.util.Log
import java.io.File
import java.util.concurrent.ConcurrentHashMap

/**
 * 任务记录存储（GET /v1/missions/{id}、GET /v1/missions?limit=10）。
 * 只保留内存 + 简单 JSON 落盘（每条任务一个文件），不引入数据库依赖。
 * TODO(未确认)：照片与航点动作的精确对应依赖飞控事件（WaylineExecutingInfo/WaypointActionListener），
 * 真机阶段以 MediaDataCenter 的文件时间戳做二次对账（见 MissionExecutor.reconcilePhotos）。
 */
object MissionStore {

    private const val TAG = "MissionStore"
    private val records = ConcurrentHashMap<String, MissionRecord>()
    private val order = ArrayDeque<String>()

    fun init() {
        // 骨架阶段不反序列化历史文件；真机阶段可在此扫描 external files dir 恢复
    }

    fun put(record: MissionRecord) {
        records[record.missionId] = record
        if (order.size > 50) order.removeFirst()
        order.addLast(record.missionId)
        persist(record)
    }

    fun get(missionId: String): MissionRecord? = records[missionId]

    fun latest(): MissionRecord? = order.lastOrNull()?.let { records[it] }

    fun list(limit: Int = 10): List<MissionRecord> =
        order.toList().asReversed().take(limit).mapNotNull { records[it] }

    private fun persist(record: MissionRecord) {
        try {
            val ctx = BridgeRuntime.appContext
            val dir = File(ctx.getExternalFilesDir(null), "missions")
            dir.mkdirs()
            File(dir, record.missionId + ".json").writeText(record.toJson().toString())
        } catch (t: Throwable) {
            Log.w(TAG, "persist mission failed: " + t.message)
        }
    }
}
