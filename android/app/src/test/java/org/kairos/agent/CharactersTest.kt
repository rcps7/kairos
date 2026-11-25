// SPDX-License-Identifier: GPL-3.0-or-later
// Ported from tests/test_characters_browser.py
package org.kairos.agent

import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.agent.CharacterRegistry
import java.io.File

class CharactersTest {
    private fun registry() = CharacterRegistry(CharacterRegistry.parsePack(File("src/main/assets/characters.json").readText()))

    @Test fun builtinsHaveBrowserControl() {
        val r = registry()
        for (id in listOf("general", "electronic_specialist", "medical_assistant", "ai_expert", "astrophysics_expert"))
            assertTrue(id, r.can("browser_control", id))
    }

    @Test fun allEightPresetsLoaded() { assertEquals(8, registry().all.size) }

    @Test fun nullCapabilitiesMeansAll() {
        val r = registry()
        val custom = r.get("general")!!.copy(id = "x", capabilities = null)
        val r2 = CharacterRegistry(CharacterRegistry.parsePack(File("src/main/assets/characters.json").readText()), listOf(custom))
        assertTrue(r2.can("email_send", "x"))
        assertEquals(r.allCapabilities, r2.capabilities("x"))
    }

    @Test fun restrictedCapabilities() {
        val pack = CharacterRegistry.parsePack(File("src/main/assets/characters.json").readText())
        val r = CharacterRegistry(pack, listOf(pack.presets[0].copy(id = "only_search", capabilities = listOf("web_search"))))
        r.activeId = "only_search"
        assertTrue(r.can("web_search")); assertFalse(r.can("memory"))
    }

    @Test fun slugAndIdRules() {
        assertEquals("my_cool_agent", CharacterRegistry.slugify("My Cool Agent!"))
        assertTrue(CharacterRegistry.validId("abc_1")); assertFalse(CharacterRegistry.validId("Bad-Id"))
    }
}
