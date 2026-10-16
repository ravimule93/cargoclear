package com.cargoclear.japac.ui.viewer

import android.app.ActivityManager
import android.content.Context
import com.cargoclear.japac.core.model.pixelBudget

/** The most pixels one bitmap of the viewer may have on this phone, from its app heap limit (see [pixelBudget]). */
fun Context.bitmapBudget(): Long = pixelBudget(getSystemService(ActivityManager::class.java).memoryClass)
