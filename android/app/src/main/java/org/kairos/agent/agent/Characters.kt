// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Port of kairos/characters.py + characters_presets.py.
package org.kairos.agent.agent

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
data class CharacterProfile(
    val id: String,
    val name: String,
    val icon: String? = null,
    val description: String = "",
    val system_prompt: String = "",
    val disclaimer: String? = null,
    /** null = all capabilities (same semantics as desktop). */
    val capabilities: List<String>? = null,
    /** null = all skills. */
    val skills: List<String>? = null,
)

@Serializable
data class CharacterPack(
    val capabilities: List<String>,
    val labels: Map<String, String>,
    val presets: List<CharacterProfile>,
)

class CharacterRegistry(pack: CharacterPack, custom: List<CharacterProfile> = emptyList()) {
    val allCapabilities = pack.capabilities
    val labels = pack.labels
    private val byId = LinkedHashMap<String, CharacterProfile>().apply {
        pack.presets.forEach { put(it.id, it) }
        custom.forEach { put(it.id, it) }
    }
    var activeId: String = GENERAL_ID

    val all: List<CharacterProfile> get() = byId.values.toList()
    fun get(id: String) = byId[id]
    fun active(): CharacterProfile = byId[activeId] ?: byId[GENERAL_ID] ?: all.first()

    fun capabilities(id: String? = null): List<String> {
        val caps = (if (id != null) get(id) else active())?.capabilities
        return caps ?: allCapabilities
    }

    fun can(capability: String, id: String? = null): Boolean {
        val caps = (if (id != null) get(id) else active())?.capabilities ?: return true
        return capability in caps
    }

    fun allowsSkill(name: String, id: String? = null): Boolean {
        val skills = (if (id != null) get(id) else active())?.skills ?: return true
        return name in skills
    }

    companion object {
        const val GENERAL_ID = "general"
        private val ID_RE = Regex("^[a-z0-9_]+$")
        private val json = Json { ignoreUnknownKeys = true }

        fun parsePack(text: String): CharacterPack = json.decodeFromString(CharacterPack.serializer(), text)

        fun slugify(name: String): String =
            name.lowercase().replace(Regex("[^a-z0-9]+"), "_").trim('_').ifEmpty { "character" }

        fun validId(id: String) = ID_RE.matches(id)
    }
}
