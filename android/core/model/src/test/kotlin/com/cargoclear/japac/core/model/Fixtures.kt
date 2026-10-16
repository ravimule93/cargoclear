package com.cargoclear.japac.core.model

import kotlinx.serialization.json.Json

/** Reads the recorded backend payloads (android/fixtures, put on the test classpath by build.gradle.kts). */
object Fixtures {
    /** Strict on purpose: a field the backend sends that the DTOs do not name fails the test, so API drift shows up here first. */
    val strict = Json { ignoreUnknownKeys = false }

    fun text(name: String): String =
        checkNotNull(Fixtures::class.java.classLoader.getResourceAsStream(name)) { "missing test resource $name" }
            .bufferedReader().use { it.readText() }

    inline fun <reified T> decode(name: String): T = strict.decodeFromString(text(name))

    inline fun <reified T> parse(json: String): T = strict.decodeFromString(json)
}
