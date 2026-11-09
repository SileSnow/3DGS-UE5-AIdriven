# DJI MSDK v5 官方 sample 在 release 下使用 minifyEnabled=true；本骨架 release 关闭混淆。
# 若开启混淆，至少需要保留 MSDK Key/Value 类与 JNIProguardKeepTag 标记的类。
# 官方参考：https://developer.dji.com/doc/mobile-sdk-tutorial/en/quick-start/run-sample.html
-keep class dji.** { *; }
-keep class com.dji.** { *; }
-keep class dji.sdk.keyvalue.** { *; }
-keep class dji.v5.** { *; }
-dontwarn dji.**
