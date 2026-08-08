package com.equitysignal.core.network

import okhttp3.HttpUrl
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The user types a backend URL into Settings; every request must land on it.
 *
 * These run without a socket: a terminal interceptor captures the URL the chain would
 * have dialled and answers with a canned response.
 */
class BaseUrlInterceptorTest {

    /** What Retrofit builds from its compiled-in default base URL. */
    private val outgoing = "http://10.0.2.2:8000/api/v1/alerts?limit=5"

    private fun urlFor(configuredBase: String, request: String = outgoing): HttpUrl {
        var captured: HttpUrl? = null
        val terminal = Interceptor { chain ->
            captured = chain.request().url
            Response.Builder()
                .request(chain.request())
                .protocol(Protocol.HTTP_1_1)
                .code(200)
                .message("OK")
                .body("{}".toResponseBody(null))
                .build()
        }
        val client = OkHttpClient.Builder()
            .addInterceptor(BaseUrlInterceptor { configuredBase })
            .addInterceptor(terminal)
            .build()
        client.newCall(Request.Builder().url(request).build()).execute().close()
        return requireNonNull(captured)
    }

    private fun requireNonNull(url: HttpUrl?): HttpUrl = url ?: error("no request reached the chain")

    @Test
    fun `rewrites scheme host and port to the configured backend`() {
        val url = urlFor("https://signals.example.com/api/v1/")

        assertEquals("https", url.scheme)
        assertEquals("signals.example.com", url.host)
        assertEquals(443, url.port)
        assertEquals("/api/v1/alerts", url.encodedPath)
        assertEquals("limit=5", url.query)
    }

    @Test
    fun `keeps an explicit port`() {
        val url = urlFor("http://192.168.1.40:8000/api/v1/")

        assertEquals("192.168.1.40", url.host)
        assertEquals(8000, url.port)
        assertEquals("/api/v1/alerts", url.encodedPath)
    }

    @Test
    fun `preserves a subpath when the backend sits behind a shared reverse proxy`() {
        // https://example.com/equity/api/v1/ must not collapse to /api/v1/ — that is the
        // difference between reaching the API and hitting whatever else the proxy serves
        // at the root.
        val url = urlFor("https://example.com/equity/api/v1/")

        assertEquals("/equity/api/v1/alerts", url.encodedPath)
    }

    @Test
    fun `a bare host with no path still resolves`() {
        val url = urlFor("https://example.com/")

        assertEquals("/api/v1/alerts", url.encodedPath)
    }

    @Test
    fun `a host typed without a scheme defaults to https`() {
        // Silently downgrading a typo'd URL to cleartext is how a shipped build ends up
        // sending its API key in the clear.
        val url = urlFor("example.com/api/v1/")

        assertEquals("https", url.scheme)
        assertEquals("example.com", url.host)
    }

    @Test
    fun `a blank setting leaves the request untouched`() {
        val url = urlFor("")

        assertEquals("10.0.2.2", url.host)
        assertEquals(8000, url.port)
        assertEquals("/api/v1/alerts", url.encodedPath)
    }

    @Test
    fun `an unparseable setting leaves the request untouched rather than failing the call`() {
        val url = urlFor("http://")  // a scheme with no host: unparseable

        assertEquals("10.0.2.2", url.host)
    }
}
