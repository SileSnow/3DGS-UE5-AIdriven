// LLM Tool-Call -> DJI MSDK v5 Android Bridge
// 工程骨架：仅依赖官方 AAR（Maven Central）。MSDK v5 仅支持 Android，且需要 RC-N2/RC-N3 等可夹手机的遥控器。
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()   // com.dji:dji-sdk-v5-aircraft:5.20.1 等 AAR 在 Maven Central（官方 README 指明 implementation 坐标）
    }
}

rootProject.name = "llmdrone-msdk-bridge"
include(":app")
