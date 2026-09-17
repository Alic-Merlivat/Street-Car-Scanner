package com.streetwatch.capture

import android.util.Log
import java.io.IOException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response

private const val TAG = "StreetWatchUpload"

/**
 * Posts JPEG frames to the street-watch server. At most one upload is kept
 * in flight; frames captured while an upload is still pending are dropped
 * rather than queued, since a stale frame from a car that already passed
 * isn't worth sending.
 */
class FrameUploader(private val serverUrl: String) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(3, TimeUnit.SECONDS)
        .writeTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()

    private val inFlight = AtomicInteger(0)
    private val jpegMediaType = "image/jpeg".toMediaType()

    fun uploadFrame(jpeg: ByteArray) {
        if (inFlight.get() > 0) {
            Log.d(TAG, "skipping frame, previous upload still in flight")
            return
        }
        inFlight.incrementAndGet()

        val url = serverUrl.trimEnd('/') + "/frame"
        val request = Request.Builder()
            .url(url)
            .post(jpeg.toRequestBody(jpegMediaType))
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                Log.e(TAG, "upload to $url failed: ${e.message}", e)
                inFlight.decrementAndGet()
            }

            override fun onResponse(call: Call, response: Response) {
                Log.d(TAG, "upload to $url -> ${response.code}")
                response.close()
                inFlight.decrementAndGet()
            }
        })
    }
}
