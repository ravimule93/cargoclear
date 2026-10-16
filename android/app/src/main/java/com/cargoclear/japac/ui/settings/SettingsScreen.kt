package com.cargoclear.japac.ui.settings

import android.text.format.Formatter
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.selection.toggleable
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cargoclear.japac.R
import com.cargoclear.japac.ui.common.PlainCard
import com.cargoclear.japac.notify.rememberNotifyEnabler
import com.cargoclear.japac.ui.theme.cargo

/** What the person can choose on this phone (docs/ANDROID_APP_PLAN.md section 7). */
@Composable
fun SettingsScreen(onBack: () -> Unit, onOpenAbout: () -> Unit, viewModel: SettingsViewModel = hiltViewModel()) {
    val secure by viewModel.viewerSecure.collectAsStateWithLifecycle()
    val cacheBytes by viewModel.cacheBytes.collectAsStateWithLifecycle()
    val notify by viewModel.notifyRunFinished.collectAsStateWithLifecycle()
    var notifyDenied by rememberSaveable { mutableStateOf(false) }
    val enableNotify = rememberNotifyEnabler { on, denied ->
        notifyDenied = denied
        viewModel.setNotifyRunFinished(on)
    }
    SettingsContent(
        secure = secure,
        cacheBytes = cacheBytes,
        onBack = onBack,
        onSecureChange = viewModel::setViewerSecure,
        onClearCache = viewModel::clearCache,
        notify = notify,
        notifyDenied = notifyDenied,
        onNotifyChange = enableNotify,
        onOpenAbout = onOpenAbout,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsContent(
    secure: Boolean,
    cacheBytes: Long,
    onBack: () -> Unit,
    onSecureChange: (Boolean) -> Unit,
    onClearCache: () -> Unit,
    notify: Boolean = false,
    notifyDenied: Boolean = false,
    onNotifyChange: (Boolean) -> Unit = {},
    onOpenAbout: () -> Unit = {},
) {
    val tokens = MaterialTheme.cargo
    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.settings_title), fontWeight = FontWeight.Bold, color = tokens.text) },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.action_back)) }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = tokens.surface),
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            PlainCard {
                // the whole row is the switch, so it is one control with its label for a screen reader
                Row(
                    Modifier.fillMaxWidth().toggleable(value = secure, role = Role.Switch, onValueChange = onSecureChange),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(stringResource(R.string.settings_secure_title), color = tokens.text, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyLarge)
                        Text(stringResource(R.string.settings_secure_body), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
                    }
                    Switch(checked = secure, onCheckedChange = null)
                }
            }
            PlainCard {
                Row(
                    Modifier.fillMaxWidth().toggleable(value = notify, role = Role.Switch, onValueChange = onNotifyChange),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(stringResource(R.string.settings_notify_title), color = tokens.text, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyLarge)
                        Text(stringResource(R.string.settings_notify_body), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
                    }
                    Switch(checked = notify, onCheckedChange = null)
                }
                if (notifyDenied && !notify) {
                    Text(stringResource(R.string.settings_notify_denied), color = tokens.warn.fg, fontWeight = FontWeight.Medium, style = MaterialTheme.typography.bodySmall)
                }
            }
            PlainCard {
                Text(stringResource(R.string.settings_cache_title), color = tokens.text, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyLarge)
                Text(
                    stringResource(R.string.settings_cache_body, Formatter.formatShortFileSize(LocalContext.current, cacheBytes)),
                    color = tokens.textMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
                OutlinedButton(onClick = onClearCache, enabled = cacheBytes > 0, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.settings_cache_clear), color = tokens.text, fontWeight = FontWeight.SemiBold)
                }
            }
            PlainCard {
                Column(Modifier.fillMaxWidth().clickable(role = Role.Button, onClick = onOpenAbout), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(stringResource(R.string.settings_about), color = tokens.text, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyLarge)
                    Text(stringResource(R.string.settings_about_hint), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}
