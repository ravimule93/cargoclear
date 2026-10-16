package com.cargoclear.japac.core.model

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class MetaTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun `decodes the demo meta the backend sends`() {
        val meta = json.decodeFromString<Meta>("""{"app_mode":"demo","data_source_policy":"fixtures"}""")
        assertEquals(Meta(AppMode.DEMO, "fixtures"), meta)
    }

    @Test
    fun `decodes the live meta and ignores fields it does not know`() {
        val meta = json.decodeFromString<Meta>("""{"app_mode":"live","data_source_policy":"live-only","added_later":1}""")
        assertEquals(AppMode.LIVE, meta.appMode)
    }

    @Test
    fun `a mode it does not know is an error, not a guess`() {
        assertThrows(SerializationException::class.java) {
            json.decodeFromString<Meta>("""{"app_mode":"staging","data_source_policy":"x"}""")
        }
    }

    @Test
    fun `decodes the error envelope with and without a request id`() {
        val full = json.decodeFromString<ErrorEnvelope>(
            """{"code":"NOT_FOUND","message":"Bundle 'b1' not found.","detail":{"bundle_id":"b1"},"request_id":"r-1"}""",
        )
        assertEquals("NOT_FOUND", full.code)
        assertEquals("r-1", full.requestId)

        val bare = json.decodeFromString<ErrorEnvelope>("""{"code":"HTTP_502","message":"Bad Gateway"}""")
        assertNull(bare.requestId)
        assertNull(bare.detail)
    }
}
