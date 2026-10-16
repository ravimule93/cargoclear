package com.cargoclear.japac.core.data

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

/**
 * Emits each time the phone's default network becomes available after the moment of collecting: coming back from airplane mode or a tunnel,
 * or moving from Wi-Fi to mobile data. The network that is already there when collecting starts is not a signal (reconnecting to it
 * would loop); a network that arrives when there was none is.
 */
fun Context.networkBecameAvailable(): Flow<Unit> = callbackFlow {
    val manager = getSystemService(ConnectivityManager::class.java)
    var alreadyThere = manager.activeNetwork != null
    val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            if (alreadyThere) alreadyThere = false else trySend(Unit)
        }

        override fun onLost(network: Network) {
            // whatever comes next is a new network, not the one that was there
            alreadyThere = false
        }
    }
    manager.registerDefaultNetworkCallback(callback)
    awaitClose { manager.unregisterNetworkCallback(callback) }
}
