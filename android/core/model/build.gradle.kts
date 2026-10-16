// Pure Kotlin: no Android types here. DTOs and the ported presentation logic live in this module so their tests run on the plain JVM
// and so a future non-Android client could reuse them.
plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}

kotlin {
    jvmToolchain(17)
}

sourceSets {
    test {
        resources {
            // The recorded backend payloads (android/fixtures) and the cross-language vectors (docs/schemas) are read from where they live, not copied.
            srcDir("../../fixtures")
            srcDir("../../../docs/schemas")
        }
    }
}

dependencies {
    api(libs.kotlinx.serialization.json)

    testImplementation(libs.junit)
}
