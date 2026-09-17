package com.streetwatch.capture

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat

// Referenced by literal string since it may not be present as a compile-time
// constant on every compileSdk stub; Android 17 gates any connection to a
// private/local IP range (e.g. 192.168.x.x) behind this, separately from
// plain android.permission.INTERNET.
private const val PERMISSION_LOCAL_NETWORK = "android.permission.ACCESS_LOCAL_NETWORK"

private val ZOOM_SELECTED_COLOR = Color.parseColor("#2A78D6")
private val ZOOM_UNSELECTED_COLOR = Color.parseColor("#3A3A3A")

class MainActivity : AppCompatActivity() {

    private lateinit var previewView: PreviewView
    private lateinit var serverUrlInput: EditText
    private lateinit var intervalInput: EditText
    private lateinit var startStopButton: Button
    private lateinit var statusText: TextView
    private lateinit var prefs: android.content.SharedPreferences
    private lateinit var zoomButtons: Map<Float, Button>

    private var service: StreamingService? = null
    private var bound = false
    private var isStreaming = false
    private var selectedZoom = StreamingService.DEFAULT_ZOOM_RATIO

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            service = (binder as StreamingService.LocalBinder).getService()
            bound = true
            service?.setPreviewView(previewView)
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            bound = false
            service = null
        }
    }

    private val streamingPermissionsLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { results ->
            if (results.values.all { it }) {
                startStreaming()
            } else {
                statusText.text = "Camera and local network permissions are required to stream."
            }
        }

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* best-effort */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        previewView = findViewById(R.id.previewView)
        serverUrlInput = findViewById(R.id.serverUrlInput)
        intervalInput = findViewById(R.id.intervalInput)
        startStopButton = findViewById(R.id.startStopButton)
        statusText = findViewById(R.id.statusText)

        prefs = getSharedPreferences("street_watch", Context.MODE_PRIVATE)
        serverUrlInput.setText(prefs.getString("server_url", "http://192.168.1.100:8000"))
        intervalInput.setText(prefs.getInt("interval_ms", 700).toString())

        zoomButtons = mapOf(
            1f to findViewById(R.id.zoom1Button),
            2f to findViewById(R.id.zoom2Button),
            5f to findViewById(R.id.zoom5Button),
        )
        selectedZoom = prefs.getFloat("zoom_ratio", StreamingService.DEFAULT_ZOOM_RATIO)
        zoomButtons.forEach { (ratio, button) -> button.setOnClickListener { selectZoom(ratio) } }
        updateZoomButtons()

        startStopButton.setOnClickListener {
            if (isStreaming) stopStreaming() else requestCameraPermissionAndStart()
        }

        requestNotificationPermissionIfNeeded()
    }

    private fun selectZoom(ratio: Float) {
        selectedZoom = ratio
        prefs.edit().putFloat("zoom_ratio", ratio).apply()
        updateZoomButtons()
        val applied = service?.setZoom(ratio)
        if (applied != null && applied < ratio) {
            statusText.text = "This phone tops out at ${applied}x zoom."
        }
    }

    private fun updateZoomButtons() {
        zoomButtons.forEach { (ratio, button) ->
            val color = if (ratio == selectedZoom) ZOOM_SELECTED_COLOR else ZOOM_UNSELECTED_COLOR
            button.backgroundTintList = ColorStateList.valueOf(color)
        }
    }

    override fun onStart() {
        super.onStart()
        bindService(Intent(this, StreamingService::class.java), connection, 0)
    }

    override fun onStop() {
        super.onStop()
        if (bound) {
            service?.setPreviewView(null)
            unbindService(connection)
            bound = false
        }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    private fun requestCameraPermissionAndStart() {
        val needed = listOfNotNull(
            Manifest.permission.CAMERA.takeIf {
                ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
            },
            PERMISSION_LOCAL_NETWORK.takeIf {
                ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
            },
        )
        if (needed.isEmpty()) {
            startStreaming()
        } else {
            streamingPermissionsLauncher.launch(needed.toTypedArray())
        }
    }

    private fun startStreaming() {
        val serverUrl = serverUrlInput.text.toString().trim()
        if (serverUrl.isEmpty()) {
            statusText.text = "Enter a server URL first."
            return
        }
        val intervalMs = intervalInput.text.toString().toLongOrNull() ?: 700L

        prefs.edit()
            .putString("server_url", serverUrl)
            .putInt("interval_ms", intervalMs.toInt())
            .apply()

        val intent = Intent(this, StreamingService::class.java).apply {
            action = StreamingService.ACTION_START
            putExtra(StreamingService.EXTRA_SERVER_URL, serverUrl)
            putExtra(StreamingService.EXTRA_INTERVAL_MS, intervalMs)
            putExtra(StreamingService.EXTRA_ZOOM_RATIO, selectedZoom)
        }
        ContextCompat.startForegroundService(this, intent)
        bindService(intent, connection, 0)

        isStreaming = true
        startStopButton.text = getString(R.string.stop_streaming)
        statusText.text = "Streaming to $serverUrl"
    }

    private fun stopStreaming() {
        service?.stopStreaming()
        isStreaming = false
        startStopButton.text = getString(R.string.start_streaming)
        statusText.text = "Stopped."
    }
}
