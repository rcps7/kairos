// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Captures screenshots of the main screens for the
// F-Droid listing. Run on an emulator/device; the PNGs are written to the app's external
// files dir and pulled by CI (see .github/workflows/android.yml).
package org.kairos.agent

import android.graphics.Bitmap
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class ScreenshotTest {
    @get:Rule
    val compose = createAndroidComposeRule<org.kairos.agent.ui.MainActivity>()

    private var n = 0
    private val dir: File by lazy {
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        // Internal files dir: pulled from CI with `adb exec-out run-as` (works on scoped storage).
        File(ctx.filesDir, "screenshots").apply {
            mkdirs()
            listFiles()?.forEach { it.delete() }
        }
    }

    private fun shot(name: String) {
        compose.waitForIdle()
        runCatching {
            val bmp = compose.onRoot().captureToImage().asAndroidBitmap()
            File(dir, "%02d_%s.png".format(++n, name)).outputStream()
                .use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
    }

    private fun tab(tag: String) {
        compose.onNodeWithTag(tag).performClick()
        compose.waitForIdle()
    }

    private fun moreTab(tag: String) {
        compose.onNodeWithTag("more").performClick()
        compose.onNodeWithTag(tag).performClick()
        compose.waitForIdle()
    }

    @Test
    fun captureMainScreens() {
        shot("chat")
        tab("tab_Provider"); shot("provider")
        tab("tab_Characters"); shot("characters")
        tab("tab_Library"); shot("library")
        tab("tab_Plans"); shot("plans")
        moreTab("tab_Browser"); shot("browser")
        moreTab("tab_Serial"); shot("serial")
        moreTab("tab_PC"); shot("pc")
        val files = dir.listFiles()?.filter { it.extension == "png" } ?: emptyList()
        assertTrue("no screenshots captured", files.isNotEmpty())
    }
}
