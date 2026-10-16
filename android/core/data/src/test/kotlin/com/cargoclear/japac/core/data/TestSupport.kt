package com.cargoclear.japac.core.data

import okhttp3.OkHttpClient

internal object TestResources {
    fun text(name: String): String =
        checkNotNull(TestResources::class.java.classLoader.getResourceAsStream(name)) { "missing test resource $name" }
            .bufferedReader().use { it.readText() }
}

internal fun testClient(): OkHttpClient = OkHttpClient.Builder().addInterceptor(RequestIdInterceptor()).build()
