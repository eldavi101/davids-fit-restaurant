// Generated to a single consistent shape; see docs/ANDROID_ARCHITECTURE.md for the
// dependency rules these declarations enforce.
plugins {
    alias(libs.plugins.kotlin.jvm)
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

dependencies {
    api(project(":core:model"))
    implementation(libs.kotlinx.coroutines.core)
    // javax.inject only — Hilt's processor runs in :app, so this module stays framework-free
    implementation("javax.inject:javax.inject:1")

    testImplementation(libs.junit)
    testImplementation(libs.turbine)
    testImplementation(libs.kotlinx.coroutines.test)
}
