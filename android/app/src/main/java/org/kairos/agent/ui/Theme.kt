// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. A polished Material 3 theme with light/dark
// and the desktop KAIROS fluorescent-green accent. Optionally follows system colours.
package org.kairos.agent.ui

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight

// Brand palette (desktop KAIROS: fluorescent green on a near-black surface).
private val Green = Color(0xFF00E676)
private val GreenDark = Color(0xFF0A3D1F)
private val Cyan = Color(0xFF4DD0E1)

val KairosDark = darkColorScheme(
    primary = Green,
    onPrimary = Color(0xFF00300F),
    primaryContainer = GreenDark,
    onPrimaryContainer = Color(0xFF9DFFC4),
    secondary = Cyan,
    onSecondary = Color(0xFF00313A),
    background = Color(0xFF0E1116),
    onBackground = Color(0xFFE6EDF3),
    surface = Color(0xFF151A21),
    onSurface = Color(0xFFE6EDF3),
    surfaceVariant = Color(0xFF1D242E),
    onSurfaceVariant = Color(0xFFB6C2CF),
    outline = Color(0xFF3A4452),
    outlineVariant = Color(0xFF262E39),
    error = Color(0xFFFF6B6B),
    onError = Color(0xFF340000),
    errorContainer = Color(0xFF5C1A1A),
    onErrorContainer = Color(0xFFFFDAD6),
)

val KairosLight = lightColorScheme(
    primary = Color(0xFF00864A),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFA6F4C5),
    onPrimaryContainer = Color(0xFF00210F),
    secondary = Color(0xFF00707E),
    background = Color(0xFFF7F9FB),
    onBackground = Color(0xFF11151A),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF11151A),
    surfaceVariant = Color(0xFFE7ECF2),
    onSurfaceVariant = Color(0xFF414B57),
    outline = Color(0xFFB9C2CD),
    error = Color(0xFFB3261E),
)

private val KairosTypography = Typography().let { base ->
    base.copy(
        titleLarge = base.titleLarge.copy(fontWeight = FontWeight.SemiBold),
        titleMedium = base.titleMedium.copy(fontWeight = FontWeight.SemiBold),
        labelSmall = base.labelSmall.copy(fontFamily = FontFamily.Monospace),
    )
}

@Composable
fun KairosTheme(
    useDynamicColor: Boolean = false,
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val ctx = LocalContext.current
    val colors = when {
        useDynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (darkTheme) dynamicDarkColorScheme(ctx) else dynamicLightColorScheme(ctx)
        darkTheme -> KairosDark
        else -> KairosLight
    }
    MaterialTheme(colorScheme = colors, typography = KairosTypography, content = content)
}
