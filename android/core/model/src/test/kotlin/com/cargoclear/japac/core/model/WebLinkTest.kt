package com.cargoclear.japac.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WebLinkTest {
    @Test
    fun `the UI's address is the proxy's address without the proxy path`() {
        assertEquals("https://ui.example.com", webOriginOf("https://ui.example.com/api/proxy/"))
        assertEquals("https://ui.example.com", webOriginOf("https://ui.example.com/api/proxy"))
        assertEquals("https://ui.example.com:8443", webOriginOf("  https://ui.example.com:8443/api/proxy/ "))
        assertEquals("a prefix the UI is served under is kept", "https://example.com/portal", webOriginOf("https://example.com/portal/api/proxy/"))
    }

    @Test
    fun `there is no web address when the API is not the UI's proxy`() {
        assertNull("the backend directly", webOriginOf("https://api.example.com/api/v1/"))
        assertNull("a development machine nobody else can reach", webOriginOf("http://10.0.2.2:3000/api/proxy/"))
        assertNull(webOriginOf("http://10.0.2.2:8080/api/v1/"))
        assertNull(webOriginOf("https:///api/proxy/"))
        assertNull(webOriginOf(""))
        assertNull(webOriginOf(null))
    }

    @Test
    fun `a bundle link is what the web client opens, and reads back to the same id`() {
        val link = workbenchLink("https://ui.example.com", "bnd-d0d1aa8a2370")
        assertEquals("https://ui.example.com/workbench/bnd-d0d1aa8a2370", link)
        assertEquals("bnd-d0d1aa8a2370", extractBundleId(link!!))
    }

    @Test
    fun `no link without an address or for something that is not a bundle id`() {
        assertNull(workbenchLink(null, "bnd-1"))
        assertNull(workbenchLink("https://ui.example.com", "../etc"))
        assertNull(workbenchLink("https://ui.example.com", ""))
    }
}
