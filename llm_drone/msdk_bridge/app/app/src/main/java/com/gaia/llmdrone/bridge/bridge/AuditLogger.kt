package com.gaia.llmdrone.bridge.bridge

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.ArrayDeque
import java.util.concurrent.atomic.AtomicLong

/**
 * 设备端审计（PROTOCOL.md §9.1 的子集）：每事件写 JSONL + 内存环形缓冲供 GET /v1/audit?since_seq=N。
 * 不可关闭（SafetyGuard 的拒绝/放行都必须落审计）。
 * 落盘路径：App external files dir / audit / audit_<run_id>.jsonl（可用 adb pull 取回）。
 */
object AuditLogger {

    private const val TAG = "AuditLogger"
    private const val MAX_BUFFER = 2000

    private val seq = AtomicLong(0)
    private val buffer = ArrayDeque<JSONObject>()
    private val lock = Any()

    @Volatile private var file: File? = null
    @Volatile private var runId: String = "default"

    fun init(appContext: android.content.Context, runId: String) {
        this.runId = runId
        val dir = File(appContext.getExternalFilesDir(null), "audit")
        dir.mkdirs()
        file = File(dir, "audit_" + runId + ".jsonl")
        Log.i(TAG, "audit file: " + file?.absolutePath)
    }

    fun events(runId: String = "default") {
        this.runId = runId
    }

    fun append(event: String, fields: JSONObject = JSONObject()) {
        val n = seq.incrementAndGet()
        val obj = JSONObject().apply {
            put("ts", BridgeRuntime.nowIso())
            put("seq", n)
            put("run_id", runId)
            put("event", event)
            fields.keys().forEach { k -> put(k, fields.get(k)) }
        }
        synchronized(lock) {
            buffer.addLast(obj)
            while (buffer.size > MAX_BUFFER) buffer.removeFirst()
            try {
                file?.appendText(obj.toString() + "\n")
            } catch (t: Throwable) {
                Log.w(TAG, "write audit failed: " + t.message)
            }
        }
    }

    fun eventsSince(sinceSeq: Long, limit: Int = 200): Pair<JSONArray, Long> {
        val arr = JSONArray()
        var last = sinceSeq
        synchronized(lock) {
            buffer.forEach { e ->
                val s = e.optLong("seq", 0)
                if (s > sinceSeq) {
                    arr.put(e)
                    last = maxOf(last, s)
                }
            }
        }
        val capped = if (arr.length() > limit) {
            JSONArray().also { out -> for (i in arr.length() - limit until arr.length()) out.put(arr.get(i)) }
        } else arr
        return Pair(capped, last)
    }
}
