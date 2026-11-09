plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.gaia.llmdrone.bridge"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.gaia.llmdrone.bridge"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        // DJI App Key：来自 gradle.properties（不要把真实 Key 提交进仓库）
        manifestPlaceholders["API_KEY"] =
            (project.findProperty("AIRCRAFT_API_KEY") as String?) ?: "Please_add_your_DJI_App_Key_here"
        manifestPlaceholders["BRIDGE_PORT"] =
            (project.findProperty("BRIDGE_HTTP_PORT") as String?) ?: "8765"

        ndk {
            // 官方 sample 只打包 arm64-v8a；桥接 App 同样只面向 arm64 手机
            abiFilters += listOf("arm64-v8a")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false // 骨架阶段关闭混淆；量产建议按官方 proguard 规则开启
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
    kotlinOptions {
        jvmTarget = "1.8"
        freeCompilerArgs += "-Xjvm-default=all"
    }

    packaging {
        // 与官方 sample 一致：MSDK 内部各 native 库重复引用 libc++_shared.so
        jniLibs.pickFirsts += listOf(
            "lib/arm64-v8a/libc++_shared.so",
            "lib/armeabi-v7a/libc++_shared.so"
        )
        // 官方 sample 要求不要 strip 的 MSDK native 库（否则运行时找不到符号）
        jniLibs.keepDebugSymbols += listOf(
            "*/*/libconstants.so", "*/*/libdji_innertools.so", "*/*/libdjibase.so",
            "*/*/libDJICSDKCommon.so", "*/*/libDJIFlySafeCore-CSDK.so", "*/*/libdjifs_jni-CSDK.so",
            "*/*/libDJIRegister.so", "*/*/libdjisdk_jni.so", "*/*/libDJIUpgradeCore.so",
            "*/*/libDJIUpgradeJNI.so", "*/*/libDJIWaypointV2Core-CSDK.so", "*/*/libdjiwpv2-CSDK.so",
            "*/*/libFlightRecordEngine.so", "*/*/libvideo-framing.so", "*/*/libwaes.so",
            "*/*/libagora-rtsa-sdk.so", "*/*/libc++.so", "*/*/libc++_shared.so",
            "*/*/libmrtc_28181.so", "*/*/libmrtc_agora.so", "*/*/libmrtc_core.so",
            "*/*/libmrtc_core_jni.so", "*/*/libmrtc_data.so", "*/*/libmrtc_log.so",
            "*/*/libmrtc_onvif.so", "*/*/libmrtc_rtmp.so", "*/*/libmrtc_rtsp.so"
        )
    }
}

dependencies {
    // ===== DJI MSDK v5（官方 README V5.20.1 给出的三个坐标） =====
    // 参考：https://raw.githubusercontent.com/dji-sdk/Mobile-SDK-Android-V5/dev-sdk-main/README.md
    implementation("com.dji:dji-sdk-v5-aircraft:5.20.1")
    compileOnly("com.dji:dji-sdk-v5-aircraft-provided:5.20.1")
    runtimeOnly("com.dji:dji-sdk-v5-networkImp:5.20.1")

    // ===== WPMZ（可选的官方 KMZ 工具库；本骨架默认自建 WPML，不强制依赖） =====
    // 官方 sample dependencies.gradle: com.dji:wpmzsdk:1.0.5.2
    // implementation("com.dji:wpmzsdk:1.0.5.2")

    // ===== 桥接层 HTTP 服务（Android 无 com.sun.net.httpserver，用 NanoHTTPD） =====
    implementation("org.nanohttpd:nanohttpd:2.3.1")

    // ===== AndroidX（MainActivity 用 AppCompat；Manifest 主题 Theme.AppCompat.NoActionBar） =====
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.core:core-ktx:1.13.1")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // ===== 仅本地 JVM 单测（不依赖真机） =====
    testImplementation("junit:junit:4.13.2")
}
