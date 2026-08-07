# Kotlinx Serialization keeps its generated serializers via companion objects.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class **$$serializer { *; }
-keepclasseswithmembers class * {
    kotlinx.serialization.KSerializer serializer(...);
}

# Retrofit interfaces and their generic signatures.
-keepattributes Signature, Exceptions
-keep,allowobfuscation interface retrofit2.Call
-keep,allowobfuscation class retrofit2.Response
-keepclasseswithmembers class * {
    @retrofit2.http.* <methods>;
}

# Room generated implementations.
-keep class * extends androidx.room.RoomDatabase { <init>(); }

# Network DTOs are reflected over by the serialization runtime.
-keep class com.equitysignal.core.network.dto.** { *; }
