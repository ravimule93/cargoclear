package com.cargoclear.japac.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.BuildConfig
import com.cargoclear.japac.R
import com.cargoclear.japac.ui.common.PlainCard
import com.cargoclear.japac.ui.common.SectionHeading
import com.cargoclear.japac.ui.theme.cargo

/**
 * What the app is and is not, how it treats the data it holds, and the open-source components it ships. The wording about what the product is
 * and is not is the claim register's (docs/CLAIMS.md C-01, C-04, C-05, C-22, C-23, C-25, C-51, C-52); the licence list is generated from the
 * release build by tools/list_licenses.py.
 */
@Composable
fun AboutScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val licences = remember { context.resources.openRawResource(R.raw.licenses).bufferedReader().use { it.readText() } }
    AboutContent(versionName = BuildConfig.VERSION_NAME, licences = licences, backend = if (BuildConfig.DEBUG) BuildConfig.API_BASE_URL.ifBlank { "(none)" } else null, onBack = onBack)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AboutContent(versionName: String, licences: String, backend: String?, onBack: () -> Unit) {
    val tokens = MaterialTheme.cargo
    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.about_title), fontWeight = FontWeight.Bold, color = tokens.text) },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.action_back)) } },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = tokens.surface),
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(stringResource(R.string.home_title), color = tokens.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleLarge)
            Text(stringResource(R.string.about_version, versionName), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
            backend?.let { Text(stringResource(R.string.dev_backend_line, it), color = tokens.textSubtle, fontFamily = FontFamily.Monospace, fontSize = 11.sp) }

            Section(R.string.about_what_title, R.string.about_what_body)
            Section(R.string.about_rules_title, R.string.about_rules_body)
            Section(R.string.about_reading_title, R.string.about_reading_body)
            Section(R.string.about_access_title, R.string.about_access_body)
            Section(R.string.about_audit_title, R.string.about_audit_body)
            Section(R.string.about_phone_title, R.string.about_phone_body)
            Section(R.string.about_scanner_title, R.string.about_scanner_body)

            PlainCard {
                SectionHeading(stringResource(R.string.about_licences_title), Modifier.semantics { heading() })
                Text(licences, color = tokens.textMuted, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun Section(title: Int, body: Int) {
    val tokens = MaterialTheme.cargo
    PlainCard {
        SectionHeading(stringResource(title), Modifier.semantics { heading() })
        Text(stringResource(body), color = tokens.text, style = MaterialTheme.typography.bodyMedium)
    }
}
