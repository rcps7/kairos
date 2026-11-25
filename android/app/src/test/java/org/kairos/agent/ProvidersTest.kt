// SPDX-License-Identifier: GPL-3.0-or-later
// Ported from tests/test_llm_models.py
package org.kairos.agent

import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.llm.Providers

class ProvidersTest {
    @Test fun modelsUrlDerivation() {
        assertEquals("https://api.openai.com/v1/models", Providers.modelsUrl("https://api.openai.com/v1/chat/completions"))
        assertEquals("https://api.deepseek.com/models", Providers.modelsUrl("https://api.deepseek.com/chat/completions"))
        assertEquals("https://api.groq.com/openai/v1/models", Providers.modelsUrl("https://api.groq.com/openai/v1/chat/completions"))
        assertEquals("https://x.example/v1/models", Providers.modelsUrl("https://x.example/v1/models"))
    }

    @Test fun fallbackModels() {
        assertTrue("kimi-k3" in Providers.fallbackModels("moonshot"))
        assertTrue("gpt-4o-mini" in Providers.fallbackModels("openai"))
        assertEquals("my-model", Providers.fallbackModels("custom", current = "my-model")[0])
    }

    @Test fun customEmptyUrlDoesNotInheritAllPresets() {
        assertEquals(emptyList<String>(), Providers.fallbackModels("custom", apiUrl = ""))
    }

    @Test fun presetsMatchDesktop() {
        assertEquals(listOf("moonshot", "deepseek", "openai", "openrouter", "groq", "custom"), Providers.PRESETS.map { it.id })
    }
}
