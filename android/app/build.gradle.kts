import com.android.build.api.variant.DeviceTestBuilder

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
    alias(libs.plugins.hilt)
}

val localApiBase = providers.gradleProperty("cargoclear.localApiBase").orElse("http://10.0.2.2:8080/api/v1/")
val hostedApiBase = providers.gradleProperty("cargoclear.hostedApiBase").orElse("")

android {
    namespace = "com.cargoclear.japac"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.cargoclear.japac"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    // Two backends, one codebase (docs/ANDROID_APP_PLAN.md section 4). "local" can sit next to "hosted" on one device.
    flavorDimensions += "backend"
    productFlavors {
        create("local") {
            dimension = "backend"
            applicationIdSuffix = ".local"
            versionNameSuffix = "-local"
            resValue("string", "app_name", "CargoClear (local)")
            buildConfigField("String", "API_BASE_URL", "\"${localApiBase.get()}\"")
        }
        create("hosted") {
            dimension = "backend"
            resValue("string", "app_name", "CargoClear")
            buildConfigField("String", "API_BASE_URL", "\"${hostedApiBase.get()}\"")
        }
    }

    // Release signing. The keystore and the passwords are NOT in this repository: give them in ~/.gradle/gradle.properties (cargoclear.release.storeFile,
    // .storePassword, .keyAlias, .keyPassword) or the environment (CARGOCLEAR_RELEASE_STORE_FILE, ..._STORE_PASSWORD, ..._KEY_ALIAS, ..._KEY_PASSWORD).
    // Without them the release build is produced unsigned, which is what a CI check wants. A keystore inside the repository is refused.
    fun releaseSetting(property: String, environment: String): String? =
        providers.gradleProperty("cargoclear.release.$property").orElse(providers.environmentVariable("CARGOCLEAR_RELEASE_${environment}")).orNull
    val releaseStore = releaseSetting("storeFile", "STORE_FILE")?.let { file(it) }
    signingConfigs {
        if (releaseStore != null) {
            require(!releaseStore.canonicalPath.startsWith(rootProject.projectDir.parentFile.canonicalPath + File.separator)) {
                "The release keystore must live outside the repository (it is at ${releaseStore.canonicalPath})."
            }
            create("release") {
                storeFile = releaseStore
                storePassword = releaseSetting("storePassword", "STORE_PASSWORD")
                keyAlias = releaseSetting("keyAlias", "KEY_ALIAS")
                keyPassword = releaseSetting("keyPassword", "KEY_PASSWORD") ?: releaseSetting("storePassword", "STORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (releaseStore != null) signingConfig = signingConfigs.getByName("release")
        }
        // The release code (R8 shrinking and obfuscation) on the LOCAL flavor, signed with the debug key, so it can be run against the demo backend:
        // the release variant of that flavor is disabled (cleartext), and a minified build that only ever launched has not shown that its serializers,
        // workers and injected classes survived shrinking. Never shipped: see beforeVariants.
        create("r8check") {
            initWith(getByName("release"))
            signingConfig = signingConfigs.getByName("debug")
            matchingFallbacks += "release"
            applicationIdSuffix = ".r8"
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
        resValues = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

// The local flavor reaches a cleartext server on the developer's machine; it must never be shipped.
androidComponents {
    beforeVariants { variant ->
        val local = variant.productFlavors.contains("backend" to "local")
        if (variant.buildType == "release" && local) variant.enable = false
        // the debug-signed minified build exists only for the local flavor: a hosted one would be a release signed with a public key
        if (variant.buildType == "r8check" && !local) variant.enable = false
    }
    // The recorded backend payloads (android/fixtures) are available to the instrumented tests as assets, read from where they live.
    // The sample PDFs of the two demo cases (fixtures/case_c, fixtures/case_d at the repository root) are there too: the viewer tests draw the boxes on them.
    onVariants { variant ->
        val assets = variant.deviceTests[DeviceTestBuilder.ANDROID_TEST_TYPE]?.sources?.assets
        assets?.addStaticSourceDirectory(rootProject.file("fixtures").path)
        assets?.addStaticSourceDirectory(rootProject.file("../fixtures").path)
    }
}

dependencies {
    implementation(project(":core:model"))
    implementation(project(":core:data"))

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.hilt.navigation.compose)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.foundation)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.core)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)
    implementation(libs.androidx.work.runtime)
    implementation(libs.androidx.hilt.work)
    ksp(libs.androidx.hilt.compiler)
    // "Scan a document" (an optional extra): on-device scanning that hands back a PDF, from Google Play services, so it is hidden where they are missing.
    implementation(libs.mlkit.document.scanner)
    implementation(libs.play.services.base)

    debugImplementation(libs.androidx.compose.ui.tooling)
    debugImplementation(libs.androidx.compose.ui.test.manifest)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.turbine)

    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.test.runner)
}
