package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.ErrorEnvelope
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

/**
 * The one door to the backend: turns every failure into an [ApiException]. Repositories call [call] and never see Retrofit or OkHttp
 * exceptions. The Retrofit instance is built on first use, so a build without a backend address never constructs a client.
 */
class Backend(
    val config: ApiConfig,
    private val client: OkHttpClient,
    private val json: Json = defaultJson,
) {
    private val api: CargoClearApi by lazy { retrofit(client).create(CargoClearApi::class.java) }

    /**
     * Same backend, more patient: an upload is answered only after the server has read, checked and stored the file, so the read timeout
     * of ordinary calls is too short for a large scan on a slow line (the browser's `fetch` has no timeout at all).
     */
    private val uploadApi: CargoClearApi by lazy {
        val patient = client.newBuilder().readTimeout(UPLOAD_READ_TIMEOUT_SECONDS, TimeUnit.SECONDS).writeTimeout(UPLOAD_WRITE_TIMEOUT_SECONDS, TimeUnit.SECONDS).build()
        retrofit(patient).create(CargoClearApi::class.java)
    }

    private fun retrofit(with: OkHttpClient): Retrofit = Retrofit.Builder()
        .baseUrl(checkNotNull(config.baseUrl) { "no backend address configured" })
        .client(with)
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build()

    suspend fun <T> call(block: suspend CargoClearApi.() -> T): T = invoke({ api }, block)

    /** Like [call], for the one request that sends a file. */
    suspend fun <T> callForUpload(block: suspend CargoClearApi.() -> T): T = invoke({ uploadApi }, block)

    private suspend fun <T> invoke(which: () -> CargoClearApi, block: suspend CargoClearApi.() -> T): T {
        if (!config.isConfigured) {
            throw ApiException(
                ErrorEnvelope(code = "NOT_CONFIGURED", message = ApiException.NOT_CONFIGURED_MESSAGE),
                ApiException.Kind.NOT_CONFIGURED,
            )
        }
        try {
            return which().block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: HttpException) {
            throw ApiException(envelopeOf(e), ApiException.Kind.HTTP, e.code(), e)
        } catch (e: SerializationException) {
            throw ApiException(
                ErrorEnvelope(code = "MALFORMED_RESPONSE", message = ApiException.MALFORMED_MESSAGE),
                ApiException.Kind.MALFORMED,
                cause = e,
            )
        } catch (e: UnreadableFileException) {
            throw ApiException(
                ErrorEnvelope(code = "FILE_UNREADABLE", message = "Could not read ${e.fileName}. The file may have been moved or deleted."),
                ApiException.Kind.LOCAL_FILE,
                cause = e,
            )
        } catch (e: FileSizeChangedException) {
            throw ApiException(
                ErrorEnvelope(code = "FILE_CHANGED", message = "${e.fileName} changed while it was being sent. Try again."),
                ApiException.Kind.LOCAL_FILE,
                cause = e,
            )
        } catch (e: IOException) {
            throw ApiException(
                ErrorEnvelope(code = "NETWORK", message = ApiException.NETWORK_MESSAGE),
                ApiException.Kind.NETWORK,
                cause = e,
            )
        }
    }

    /** Same fallbacks as `toErrorEnvelope` in frontend/lib/api.ts: a body that is not an envelope becomes `HTTP_<status>`. */
    private fun envelopeOf(e: HttpException): ErrorEnvelope {
        val fallbackMessage = e.message().takeIf { it.isNotBlank() } ?: "Request failed"
        val body = runCatching { json.parseToJsonElement(e.response()?.errorBody()?.string().orEmpty()).jsonObject }
            .getOrNull() ?: JsonObject(emptyMap())
        fun text(key: String): String? = body[key]?.let { runCatching { it.jsonPrimitive.contentOrNull }.getOrNull() }?.takeIf { it.isNotBlank() }
        return ErrorEnvelope(
            code = text("code") ?: "HTTP_${e.code()}",
            message = text("message") ?: fallbackMessage,
            detail = body["detail"],
            requestId = text("request_id"),
        )
    }

    companion object {
        private const val UPLOAD_READ_TIMEOUT_SECONDS = 120L
        private const val UPLOAD_WRITE_TIMEOUT_SECONDS = 60L

        /** Lenient about what the server adds later, strict about what it must send (enums and required fields are never guessed). */
        val defaultJson: Json = Json {
            ignoreUnknownKeys = true
            explicitNulls = false
            coerceInputValues = true
        }
    }
}
