package com.equitysignal.core.network

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import java.util.concurrent.TimeUnit
import javax.inject.Singleton
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit

/**
 * Where the client's connection settings come from.
 *
 * The Android app holds exactly one credential: the backend API key the user enters in
 * Settings. Market-data vendor keys live only on the server, so a compromised APK exposes
 * no vendor entitlement (requirement 52).
 */
interface ApiConfigProvider {
    suspend fun baseUrl(): String
    suspend fun apiKey(): String
}

/** Adds the API key and asks for a compressed response. */
class ApiKeyInterceptor(private val keyProvider: () -> String) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
        val request = chain.request().newBuilder()
            .addHeader("X-API-Key", keyProvider())
            .addHeader("Accept", "application/json")
            .addHeader("Accept-Encoding", "gzip")
            .build()
        return chain.proceed(request)
    }
}

/**
 * Lets the user change the backend URL without rebuilding Retrofit.
 *
 * Retrofit fixes its base URL at construction; rather than recreate the whole stack on
 * every settings change, this rewrites the host on each call.
 */
class BaseUrlInterceptor(private val baseUrlProvider: () -> String) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
        val configured = baseUrlProvider().trim()
        if (configured.isEmpty()) return chain.proceed(chain.request())

        // OkHttp 4 exposes these as Kotlin properties; the old Java-style accessors are
        // deprecated at ERROR level and will not compile.
        val newBase = normalize(configured).toHttpUrlOrNull()
            ?: return chain.proceed(chain.request())

        val rebuilt = chain.request().url.newBuilder()
            .scheme(newBase.scheme)
            .host(newBase.host)
            .port(newBase.port)
            .build()
        return chain.proceed(chain.request().newBuilder().url(rebuilt).build())
    }

    private fun normalize(url: String): String =
        if (url.startsWith("http://") || url.startsWith("https://")) url else "https://$url"
}

object NetworkDefaults {
    const val DEFAULT_BASE_URL = "http://10.0.2.2:8000/api/v1/"
    const val TIMEOUT_SECONDS = 30L
}

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    fun provideJson(): Json = Json {
        ignoreUnknownKeys = true      // a backend that adds a field must not break the app
        coerceInputValues = true
        explicitNulls = false
        isLenient = true
    }

    @Provides
    @Singleton
    fun provideOkHttp(
        apiKeyInterceptor: ApiKeyInterceptor,
        baseUrlInterceptor: BaseUrlInterceptor,
    ): OkHttpClient = OkHttpClient.Builder()
        .addInterceptor(baseUrlInterceptor)
        .addInterceptor(apiKeyInterceptor)
        .addInterceptor(
            HttpLoggingInterceptor().apply {
                // Headers only: request bodies would put the API key in logcat.
                level = HttpLoggingInterceptor.Level.BASIC
            }
        )
        .connectTimeout(NetworkDefaults.TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .readTimeout(NetworkDefaults.TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    @Provides
    @Singleton
    fun provideRetrofit(client: OkHttpClient, json: Json): Retrofit = Retrofit.Builder()
        .baseUrl(NetworkDefaults.DEFAULT_BASE_URL)
        .client(client)
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build()

    @Provides
    @Singleton
    fun provideApi(retrofit: Retrofit): EquitySignalApi = retrofit.create(EquitySignalApi::class.java)
}
