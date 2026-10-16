package com.cargoclear.japac.core.data

import java.util.UUID
import okhttp3.Interceptor
import okhttp3.Response

/**
 * Tags every request with an `X-Request-Id`. The UI's proxy accepts `[A-Za-z0-9._-]{1,64}` (a UUID fits), passes it on and the backend
 * echoes it in its error envelope, so a failure on a phone can be matched to the server's log line.
 */
class RequestIdInterceptor(private val newId: () -> String = { UUID.randomUUID().toString() }) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response =
        chain.proceed(chain.request().newBuilder().header(HEADER, newId()).build())

    companion object {
        const val HEADER = "X-Request-Id"
    }
}
