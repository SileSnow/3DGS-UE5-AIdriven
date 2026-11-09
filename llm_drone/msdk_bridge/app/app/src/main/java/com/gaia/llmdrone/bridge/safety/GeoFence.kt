package com.gaia.llmdrone.bridge.safety

import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min

/**
 * 地理围栏 / 禁飞区几何校验（纯 Kotlin，无 Android 依赖，方便真机前用 JVM 单测覆盖）。
 * 与 PROTOCOL.md §2 的局部坐标换算一致（111320 m/deg）。
 */
object GeoFence {

    fun distanceM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val north = (lat2 - lat1) * 111320.0
        val east = (lon2 - lon1) * 111320.0 * cos(Math.toRadians(lat1))
        return Math.sqrt(north * north + east * east)
    }

    fun insideCircle(lat: Double, lon: Double, centerLat: Double, centerLon: Double, radiusM: Double): Boolean =
        distanceM(centerLat, centerLon, lat, lon) <= radiusM

    /** 射线法判断点是否在多边形内（polygon = (lat,lon) 列表，顺序无关） */
    fun insidePolygon(lat: Double, lon: Double, polygon: List<Pair<Double, Double>>): Boolean {
        if (polygon.size < 3) return false
        var inside = false
        var j = polygon.size - 1
        for (i in polygon.indices) {
            val (latI, lonI) = polygon[i]
            val (latJ, lonJ) = polygon[j]
            val intersects = ((lonI > lon) != (lonJ > lon)) &&
                (lat < (latJ - latI) * (lon - lonI) / ((lonJ - lonI).let { if (abs(it) < 1e-12) 1e-12 else it }) + latI)
            if (intersects) inside = !inside
            j = i
        }
        return inside
    }
}
