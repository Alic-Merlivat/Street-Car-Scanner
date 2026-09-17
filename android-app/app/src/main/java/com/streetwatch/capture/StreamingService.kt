package com.streetwatch.capture

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.util.Log
import android.util.Size
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import java.io.ByteArrayOutputStream

/**
 * Owns the camera for as long as streaming is active, independent of
 * whether MainActivity is visible, so the phone can keep watching the
 * street while the screen is off or the app is backgrounded.
 */
class StreamingService : LifecycleService() {

    companion object {
        const val ACTION_START = "com.streetwatch.capture.START"
        const val ACTION_STOP = "com.streetwatch.capture.STOP"
        const val EXTRA_SERVER_URL = "server_url"
        const val EXTRA_INTERVAL_MS = "interval_ms"
        const val EXTRA_ZOOM_RATIO = "zoom_ratio"
        const val DEFAULT_ZOOM_RATIO = 2.0f
        private const val CHANNEL_ID = "street_watch_streaming"
        private const val NOTIFICATION_ID = 1
        private const val TAG = "StreetWatchService"
    }

    inner class LocalBinder : Binder() {
        fun getService(): StreamingService = this@StreamingService
    }

    private val binder = LocalBinder()

    private var cameraProvider: ProcessCameraProvider? = null
    private var camera: Camera? = null
    private var preview: Preview? = null
    private var uploader: FrameUploader? = null

    private var zoomRatio = DEFAULT_ZOOM_RATIO
    private var intervalMs = 700L
    private var lastSentAtMs = 0L
    @Volatile private var streaming = false

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onBind(intent: Intent): IBinder {
        super.onBind(intent)
        return binder
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)

        if (intent?.action == ACTION_STOP) {
            stopStreaming()
            return START_NOT_STICKY
        }

        val serverUrl = intent?.getStringExtra(EXTRA_SERVER_URL)
        if (serverUrl.isNullOrBlank()) {
            stopSelf()
            return START_NOT_STICKY
        }

        intervalMs = intent.getLongExtra(EXTRA_INTERVAL_MS, 700L)
        zoomRatio = intent.getFloatExtra(EXTRA_ZOOM_RATIO, DEFAULT_ZOOM_RATIO)
        uploader = FrameUploader(serverUrl)
        streaming = true
        Log.d(TAG, "starting stream to $serverUrl every ${intervalMs}ms")
        startForeground(NOTIFICATION_ID, buildNotification(serverUrl))
        startCamera()
        return START_STICKY
    }

    fun setPreviewView(previewView: PreviewView?) {
        preview?.setSurfaceProvider(previewView?.surfaceProvider)
    }

    /** Returns the zoom actually applied, which may be clamped to the device's max. */
    fun setZoom(ratio: Float): Float {
        zoomRatio = ratio
        return applyZoom()
    }

    private fun applyZoom(): Float {
        val cam = camera ?: return zoomRatio
        val maxZoom = cam.cameraInfo.zoomState.value?.maxZoomRatio ?: 1f
        val zoom = zoomRatio.coerceIn(1f, maxZoom)
        cam.cameraControl.setZoomRatio(zoom)
        Log.d(TAG, "zoom=${zoom}x (requested ${zoomRatio}x, device max ${maxZoom}x)")
        return zoom
    }

    fun stopStreaming() {
        streaming = false
        cameraProvider?.unbindAll()
        camera = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun startCamera() {
        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener({
            val provider = providerFuture.get()
            cameraProvider = provider

            val resolutionSelector = ResolutionSelector.Builder()
                .setResolutionStrategy(
                    ResolutionStrategy(Size(1920, 1080), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER)
                )
                .build()

            val newPreview = Preview.Builder().build()
            val analysis = ImageAnalysis.Builder()
                .setResolutionSelector(resolutionSelector)
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
            analysis.setAnalyzer(ContextCompat.getMainExecutor(this)) { proxy ->
                analyzeFrame(proxy)
            }

            provider.unbindAll()
            camera = provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, newPreview, analysis)
            preview = newPreview
            applyZoom()
            Log.d(TAG, "camera bound, analysis running")
        }, ContextCompat.getMainExecutor(this))
    }

    private fun analyzeFrame(imageProxy: ImageProxy) {
        val now = System.currentTimeMillis()
        if (!streaming || now - lastSentAtMs < intervalMs) {
            imageProxy.close()
            return
        }
        lastSentAtMs = now

        val jpeg = try {
            imageProxyToJpeg(imageProxy)
        } finally {
            imageProxy.close()
        }
        Log.d(TAG, "captured frame (${jpeg.size} bytes), handing off to uploader")
        uploader?.uploadFrame(jpeg)
    }

    /** Converts a YUV_420_888 frame to JPEG, honoring each plane's row/pixel stride. */
    private fun imageProxyToJpeg(imageProxy: ImageProxy): ByteArray {
        val width = imageProxy.width
        val height = imageProxy.height
        val nv21 = ByteArray(width * height * 3 / 2)

        val yPlane = imageProxy.planes[0]
        val uPlane = imageProxy.planes[1]
        val vPlane = imageProxy.planes[2]

        var pos = 0
        val yBuffer = yPlane.buffer
        val yRowStride = yPlane.rowStride
        for (row in 0 until height) {
            yBuffer.position(row * yRowStride)
            yBuffer.get(nv21, pos, width)
            pos += width
        }

        val uvWidth = width / 2
        val uvHeight = height / 2
        val uBuffer = uPlane.buffer
        val vBuffer = vPlane.buffer
        val uRowStride = uPlane.rowStride
        val uPixelStride = uPlane.pixelStride
        val vRowStride = vPlane.rowStride
        val vPixelStride = vPlane.pixelStride

        for (row in 0 until uvHeight) {
            for (col in 0 until uvWidth) {
                val vIndex = row * vRowStride + col * vPixelStride
                val uIndex = row * uRowStride + col * uPixelStride
                nv21[pos++] = vBuffer.get(vIndex)
                nv21[pos++] = uBuffer.get(uIndex)
            }
        }

        val yuvImage = YuvImage(nv21, ImageFormat.NV21, width, height, null)
        val out = ByteArrayOutputStream()
        yuvImage.compressToJpeg(Rect(0, 0, width, height), 80, out)
        return out.toByteArray()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Street Watch streaming",
                NotificationManager.IMPORTANCE_LOW,
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun buildNotification(serverUrl: String): Notification {
        val stopIntent = Intent(this, StreamingService::class.java).apply { action = ACTION_STOP }
        val stopPendingIntent = PendingIntent.getService(
            this, 0, stopIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Street Watch")
            .setContentText("Streaming to $serverUrl")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .addAction(0, "Stop", stopPendingIntent)
            .build()
    }
}
