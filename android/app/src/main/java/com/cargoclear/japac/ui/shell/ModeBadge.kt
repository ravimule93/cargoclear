package com.cargoclear.japac.ui.shell

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.ui.theme.StatusColors
import com.cargoclear.japac.ui.theme.cargo

/**
 * Which mode the backend runs in (port of components/shell/ModeBadge.tsx). The label always carries the meaning; the dot and tint only
 * repeat it, so it still reads without colour. Announced politely to a screen reader whenever it changes.
 */
@Composable
fun ModeBadge(state: MetaState, modifier: Modifier = Modifier) {
    val tokens = MaterialTheme.cargo
    val label: String
    val description: String
    val colors: StatusColors
    when (state) {
        MetaState.Loading -> {
            label = stringResource(R.string.mode_connecting)
            description = stringResource(R.string.mode_connecting_description)
            colors = StatusColors(tokens.textMuted, tokens.border, Color.Transparent)
        }
        is MetaState.Failed -> {
            label = stringResource(if (state.notConfigured) R.string.mode_not_configured else R.string.mode_offline)
            description = if (state.notConfigured) {
                stringResource(R.string.mode_not_configured_description)
            } else {
                stringResource(R.string.mode_offline_description, state.message)
            }
            colors = tokens.err
        }
        is MetaState.Ready -> when (state.meta.appMode) {
            AppMode.LIVE -> {
                label = stringResource(R.string.mode_live)
                description = stringResource(R.string.mode_live_description)
                colors = tokens.ok
            }
            AppMode.DEMO -> {
                label = stringResource(R.string.mode_demo)
                description = stringResource(R.string.mode_demo_description)
                colors = tokens.warn
            }
        }
    }

    Surface(
        modifier = modifier.semantics(mergeDescendants = true) {
            contentDescription = description
            liveRegion = LiveRegionMode.Polite
        },
        shape = CircleShape,
        color = colors.bg,
        border = BorderStroke(1.dp, colors.bd),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Spacer(Modifier.size(8.dp).background(colors.bd, CircleShape))
            Spacer(Modifier.width(6.dp))
            Text(
                text = label.uppercase(),
                color = colors.fg,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 0.5.sp,
            )
        }
    }
}
