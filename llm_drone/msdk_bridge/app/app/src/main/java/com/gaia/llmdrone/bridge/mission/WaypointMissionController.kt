package com.gaia.llmdrone.bridge.mission

import android.util.Log
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.manager.aircraft.waypoint3.WaylineExecutingInfoListener
import dji.v5.manager.aircraft.waypoint3.WaypointActionListener
import dji.v5.manager.aircraft.waypoint3.WaypointMissionExecuteStateListener
import dji.v5.manager.aircraft.waypoint3.WaypointMissionManager
import dji.v5.manager.aircraft.waypoint3.model.WaypointMissionExecuteState
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * 航点任务执行器（KMZ/WPML，飞控端执行，链路中断可继续）。
 *
 * 官方依据（API Reference + 官方 sample）：
 * - WaypointMissionManager（包 dji.v5.manager.aircraft.waypoint3；文档页名为 IWaypointMissionManager）：
 *   pushKMZFileToAircraft / startMission(missionFileName, waylineIDs, cb) / pauseMission / resumeMission /
 *   stopMission / getAvailableWaylineIDs / addWaypointMissionExecuteStateListener /
 *   addWaylineExecutingInfoListener / addWaypointActionListener：
 *   https://developer.dji.com/api-reference-v5/android-api/Components/IWaypointMissionManager/IWaypointMissionManager.html
 *   https://raw.githubusercontent.com/dji-sdk/Mobile-SDK-Android-V5/dev-sdk-main/SampleCode-V5/android-sdk-v5-sample/src/main/java/dji/sampleV5/aircraft/models/WayPointV3VM.kt
 * - WaypointMissionExecuteState 枚举（IDLE/READY/UPLOADING/PREPARING/ENTER_WAYLINE/EXECUTING/INTERRUPTED/
 *   RECOVERING/FINISHED/NOT_SUPPORTED）同页面。
 *
 * 未执行边界：未编译、未真机验证；WaylineExecutingInfo 的字段名以 API Reference 为准（TODO 未确认）。
 */
object WaypointMissionController {

    private const val TAG = "WaypointMission"

    private val manager: WaypointMissionManager get() = WaypointMissionManager.getInstance()

    @Volatile var currentMissionFileName: String? = null
        private set
    @Volatile var executeState: WaypointMissionExecuteState = WaypointMissionExecuteState.IDLE
        private set
    @Volatile var currentWaypointIndex: Int = -1
        private set

    private var completion: CompletableDeferred<Boolean>? = null
    private var stateListener: WaypointMissionExecuteStateListener? = null
    private var infoListener: WaylineExecutingInfoListener? = null
    private var actionListener: WaypointActionListener? = null

    /** 上传 KMZ（进度回调 -> 0-100） */
    suspend fun upload(kmzPath: String, onProgress: (Double) -> Unit): Result<Unit> =
        suspendCancellableCoroutine { cont ->
            try {
                manager.pushKMZFileToAircraft(kmzPath, object :
                    CommonCallbacks.CompletionCallbackWithProgress<Double> {
                    override fun onProgressUpdate(progress: Double) {
                        onProgress(progress)
                    }
                    override fun onSuccess() {
                        cont.resume(Result.success(Unit))
                    }
                    override fun onFailure(error: IDJIError) {
                        cont.resume(Result.failure(IllegalStateException("upload KMZ: " + error)))
                    }
                })
            } catch (t: Throwable) {
                cont.resume(Result.failure(t))
            }
        }

    /** 开始任务，返回的 Deferred 在 FINISHED（或失败）时完成 */
    // TODO(未确认)：08 官方 sample 传 KMZ **路径**（missionPath）；API 页字段名写 missionFileName。
    // 本实现按 sample 语义传路径，真机以实际接受为准。
    fun start(kmzPath: String, onOutcome: (Boolean) -> Unit): CompletableDeferred<Boolean> {
        currentMissionFileName = kmzPath
        val deferred = CompletableDeferred<Boolean>()
        completion = deferred
        registerListeners()

        val waylineIds = try {
            manager.getAvailableWaylineIDs(kmzPath) ?: emptyList()
        } catch (t: Throwable) {
            Log.w(TAG, "getAvailableWaylineIDs failed: " + t.message); emptyList()
        }
        try {
            manager.startMission(kmzPath, waylineIds, object : CommonCallbacks.CompletionCallback {
                override fun onSuccess() {
                    Log.i(TAG, "startMission accepted, waylines=" + waylineIds)
                }
                override fun onFailure(error: IDJIError) {
                    Log.e(TAG, "startMission failed: " + error)
                    if (!deferred.isCompleted) deferred.complete(false)
                    onOutcome(false)
                }
            })
        } catch (t: Throwable) {
            Log.e(TAG, "startMission exception: " + t.message)
            if (!deferred.isCompleted) deferred.complete(false)
        }
        return deferred
    }

    suspend fun pause(): Result<Unit> = callbackCall("pauseMission") { cb ->
        manager.pauseMission(cb)
    }

    suspend fun resume(): Result<Unit> = callbackCall("resumeMission") { cb ->
        manager.resumeMission(cb)
    }

    suspend fun stop(): Result<Unit> {
        val name = currentMissionFileName ?: return Result.success(Unit)
        return callbackCall("stopMission") { cb -> manager.stopMission(name, cb) }
    }

    fun cleanup() {
        try {
            manager.clearAllWaypointMissionExecuteStateListener()
            manager.clearAllWaylineExecutingInfoListener()
            manager.clearAllWaypointActionListener()
        } catch (t: Throwable) {
            Log.w(TAG, "cleanup listeners failed: " + t.message)
        }
        stateListener = null; infoListener = null; actionListener = null
    }

    // docs/research/08 §6.2 复核：三个 Listener 都是普通 interface，必须 object 实现具名方法（不能用 lambda）。
    private fun registerListeners() {
        stateListener = object : WaypointMissionExecuteStateListener {
            override fun onMissionStateUpdate(missionState: WaypointMissionExecuteState) {
                executeState = missionState
                Log.i(TAG, "mission state=" + missionState)
                when (missionState) {
                    WaypointMissionExecuteState.FINISHED -> {
                        completion?.let { if (!it.isCompleted) it.complete(true) }
                        cleanup()
                    }
                    WaypointMissionExecuteState.INTERRUPTED,
                    WaypointMissionExecuteState.NOT_SUPPORTED ->
                        completion?.let { if (!it.isCompleted) it.complete(false) }
                    else -> Unit
                }
            }
        }.also { manager.addWaypointMissionExecuteStateListener(it) }

        infoListener = object : WaylineExecutingInfoListener {
            override fun onWaylineExecutingInfoUpdate(info: dji.v5.manager.aircraft.waypoint3.model.WaylineExecutingInfo?) {
                // 08 §6.2：WaylineExecutingInfo 提供 getMissionFileName()/getWaylineID()/getCurrentWaypointIndex()
                currentWaypointIndex = try { info?.currentWaypointIndex ?: -1 } catch (t: Throwable) { -1 }
                Log.v(TAG, "wayline executing info: " + info)
            }
        }.also { manager.addWaylineExecutingInfoListener(it) }

        actionListener = object : WaypointActionListener {
            override fun onExecutionStart(actionGroup: Int, actionId: Int) {
                Log.d(TAG, "action start group=" + actionGroup + " id=" + actionId)
            }
            override fun onExecutionFinish(actionGroup: Int, actionId: Int, error: IDJIError?) {
                if (error != null) Log.w(TAG, "action finish error group=" + actionGroup + " id=" + actionId + ": " + error)
            }
        }.also { manager.addWaypointActionListener(it) }
    }

    private suspend fun callbackCall(
        where: String,
        invoke: (CommonCallbacks.CompletionCallback) -> Unit
    ): Result<Unit> = suspendCancellableCoroutine { cont ->
        try {
            invoke(object : CommonCallbacks.CompletionCallback {
                override fun onSuccess() = cont.resume(Result.success(Unit))
                override fun onFailure(error: IDJIError) =
                    cont.resume(Result.failure(IllegalStateException(where + ": " + error)))
            })
        } catch (t: Throwable) {
            cont.resume(Result.failure(t))
        }
    }
}
