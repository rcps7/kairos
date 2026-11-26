// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Replaces the desktop OS keyring.
package org.kairos.agent.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Secrets (API keys, tokens, passwords) are encrypted with an AES-256-GCM key that lives in the
 * Android Keystore and never leaves it. Only ciphertext is written to app-private preferences.
 */
class SecureStore(context: Context) {
    private val prefs = context.getSharedPreferences("kairos_secrets", Context.MODE_PRIVATE)

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getEntry(ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return gen.generateKey()
    }

    fun put(name: String, value: String?) {
        if (value.isNullOrEmpty()) { prefs.edit().remove(name).apply(); return }
        val c = Cipher.getInstance(TRANSFORM).apply { init(Cipher.ENCRYPT_MODE, key()) }
        val ct = c.doFinal(value.toByteArray(Charsets.UTF_8))
        val blob = Base64.encodeToString(c.iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(ct, Base64.NO_WRAP)
        prefs.edit().putString(name, blob).apply()
    }

    fun get(name: String): String? {
        val blob = prefs.getString(name, null) ?: return null
        return runCatching {
            val (iv, ct) = blob.split(":", limit = 2).map { Base64.decode(it, Base64.NO_WRAP) }
            val c = Cipher.getInstance(TRANSFORM).apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv)) }
            String(c.doFinal(ct), Charsets.UTF_8)
        }.getOrNull()
    }

    companion object {
        private const val ALIAS = "kairos_master_key"
        private const val TRANSFORM = "AES/GCM/NoPadding"
        fun apiKeyName(providerId: String) = "llm_api_key_$providerId"
        const val EMAIL_PASSWORD = "email_password"
        const val TELEGRAM_TOKEN = "telegram_token"
        const val GIT_TOKEN = "git_token"
    }
}
