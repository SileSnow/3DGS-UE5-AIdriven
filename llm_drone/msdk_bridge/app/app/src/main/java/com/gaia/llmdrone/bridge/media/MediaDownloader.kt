package com.gaia.llmdrone.bridge.media

import android.util.Log
import com.gaia.llmdrone.bridge.bridge.BridgeRuntime
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.manager.datacenter.MediaDataCenter
import dji.v5.manager.datacenter.media.MediaFile
import dji.v5.manager.datacenter.media.MediaFileDownloadListener
import dji.v5.manager.datacenter.media.MediaFileListData
import dji.v5.manager.datacenter.media.MediaFileListDataSource
import dji.v5.manager.datacenter.media.MediaFileListState
import dji.v5.manager.datacenter.media.PullMediaFileListParam
import dji.sdk.keyvalue.value.common.ComponentIndexType
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * 媒体文件列表与下载（3DGS 数据回收）。
 *
 * 官方依据：
 * - IMediaManager.pullMediaFileListFromCamera(PullMediaFileListParam, callback)、mediaFileListData、
 *   addMediaFileListStateListener、setMediaFileDataSource(MediaFileListDataSource)、enable/disable：
 *   https://developer.dji.com/api-reference-v5/android-api/Components/IMediaDataCenter/IMediaManager.html
 * - MediaFile.pullOriginalMediaFileFromCamera(offset, MediaFileDownloadListener) 官方 sample：
 *   https://raw.githubusercontent.com/dji-sdk/Mobile-SDK-Android-V5/dev-sdk-main/SampleCode-V5/android-sdk-v5-sample/src/main/java/dji/sampleV5/aircraft/models/MediaVM.kt
 *
 * 未执行边界：未编译、未真机；照片时间戳字段在 MediaFile 上的确切属性名未核实（TODO(未确认)），
 * listNewFilesSince 目前返回"当前列表全部文件"，真机阶段必须补时间过滤，否则会误把历史照片当成本任务照片。
 */
object MediaDownloader {

    private const val TAG = "MediaDownloader"
    private const val PAGE_SIZE = 100

    @Volatile private var lastList: MediaFileListData? = null

    fun init(appContext: android.content.Context) {
        try {
            MediaDataCenter.getInstance().mediaManager.addMediaFileListStateListener { state ->
                if (state == MediaFileListState.UP_TO_DATE) {
                    lastList = MediaDataCenter.getInstance().mediaManager.mediaFileListData
                    Log.i(TAG, "media list updated, n=" + (lastList?.data?.size ?: 0))
                }
            }
            val source = MediaFileListDataSource.Builder()
                .setIndexType(ComponentIndexType.LEFT_OR_MAIN)
                .build()
            MediaDataCenter.getInstance().mediaManager.setMediaFileDataSource(source)
        } catch (t: Throwable) {
            Log.w(TAG, "media init failed: " + t.message)
        }
    }

    /** 08 §6.5：媒体列表/下载前需 enable() 进入回放/下载模式（IMediaManager.enable） */
    private suspend fun enableMediaPlayback() {
        suspendCancellableCoroutine { cont ->
            try {
                MediaDataCenter.getInstance().mediaManager.enable(object : CommonCallbacks.CompletionCallback {
                    override fun onSuccess() { cont.resume(Unit) }
                    override fun onFailure(error: IDJIError) {
                        Log.w(TAG, "media enable failed: " + error); cont.resume(Unit)
                    }
                })
            } catch (t: Throwable) {
                Log.w(TAG, "media enable exception: " + t.message); cont.resume(Unit)
            }
        }
    }

    suspend fun refreshList(): List<MediaFile> {
        enableMediaPlayback()
        try {
            MediaDataCenter.getInstance().mediaManager.pullMediaFileListFromCamera(
                PullMediaFileListParam.Builder().mediaFileIndex(0).count(PAGE_SIZE).build(),
                object : CommonCallbacks.CompletionCallback {
                    override fun onSuccess() { Log.i(TAG, "pull media list success") }
                    override fun onFailure(error: IDJIError) { Log.w(TAG, "pull media list failed: " + error) }
                }
            )
        } catch (t: Throwable) {
            Log.w(TAG, "pull media list exception: " + t.message)
        }
        // 等待 MediaFileListStateListener 回调（最多 10s）
        repeat(50) {
            val data = lastList?.data
            if (!data.isNullOrEmpty()) return data
            delay(200L)
        }
        return lastList?.data ?: emptyList()
    }

    /**
     * 最近新增照片（供 MissionExecutor 对账）。
     * TODO(未确认)：MediaFile 的创建时间属性名；当前实现返回列表里"视频以外"的全部文件，
     * 真机阶段需按 MediaFile 时间戳 > sinceMs 且类型为 PHOTO 过滤。
     */
    fun listNewFilesSince(sinceMs: Long): List<MediaFile> {
        val files = lastList?.data ?: return emptyList()
        return files.filter { f ->
            val name = f.fileName ?: ""
            !name.endsWith(".MP4", true) && !name.endsWith(".MOV", true)
        }
    }

    /** 下载最新 n 张照片到 App external files dir / photos /；返回本地路径列表。 */
    suspend fun downloadNewest(nPhotos: Int): List<File> {
        val files = refreshList().filter { f ->
            val name = f.fileName ?: ""
            !name.endsWith(".MP4", true) && !name.endsWith(".MOV", true)
        }.take(nPhotos)
        val outDir = File(BridgeRuntime.appContext.getExternalFilesDir(null), "photos").apply { mkdirs() }
        val out = mutableListOf<File>()
        for (f in files) {
            val dest = File(outDir, f.fileName ?: ("media_" + f.fileIndex + ".jpg"))
            val ok = download(f, dest)
            if (ok) out.add(dest)
        }
        return out
    }

    private suspend fun download(mediaFile: MediaFile, dest: File): Boolean =
        suspendCancellableCoroutine { cont ->
            var success = false
            try {
                val fos = FileOutputStream(dest, false)
                val bos = BufferedOutputStream(fos)
                mediaFile.pullOriginalMediaFileFromCamera(0L, object : MediaFileDownloadListener {
                    override fun onStart() { Log.i(TAG, "download start: " + mediaFile.fileName) }
                    override fun onProgress(total: Long, current: Long) {}
                    override fun onRealtimeDataUpdate(data: ByteArray, position: Long) {
                        try {
                            bos.write(data)
                        } catch (e: IOException) {
                            Log.e(TAG, "write error: " + e.message)
                        }
                    }
                    override fun onFinish() {
                        try { bos.flush(); bos.close(); fos.close() } catch (e: IOException) {
                            Log.w(TAG, "close error: " + e.message)
                        }
                        success = true
                        cont.resume(true)
                    }
                    override fun onFailure(error: IDJIError?) {
                        Log.w(TAG, "download failed: " + error)
                        try { bos.close(); fos.close() } catch (e: IOException) { /* ignore */ }
                        cont.resume(false)
                    }
                })
            } catch (t: Throwable) {
                Log.e(TAG, "download exception: " + t.message)
                cont.resume(false)
            }
        }
}
