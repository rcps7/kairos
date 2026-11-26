// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Voice: speech-to-text (Talk) with a live level meter and
// spoken replies. Desktop uses speech_recognition + pyttsx3 (kairos/gui/voice_widgets.py); Android
// uses the platform SpeechRecognizer and TextToSpeech, so no extra dependency is needed.
package org.kairos.agent.voice

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import java.util.Locale

object VoiceText {
    /** Turn a chat reply into something pleasant to hear: no code blocks, markdown, URLs or tool markup. */
    fun forSpeech(text: String, maxChars: Int = 3000): String = text
        .replace(Regex("```.*?```", RegexOption.DOT_MATCHES_ALL), " (code omitted) ")
        .replace(Regex("<tool[^>]*>.*?</tool>", RegexOption.DOT_MATCHES_ALL), " ")
        .replace(Regex("`([^`]*)`"), "$1")
        .replace(Regex("!?\\[([^\\]]*)]\\([^)]*\\)"), "$1")
        .replace(Regex("https?://\\S+"), " link ")
        .replace(Regex("(?m)^\\s{0,3}#{1,6}\\s*"), "")
        .replace(Regex("(?m)^\\s*[-*+]\\s+"), "")
        .replace(Regex("[*_~]{1,3}"), "")
        .replace(Regex("[ \\t]+"), " ")
        .replace(Regex("\\n{2,}"), "\n")
        .trim()
        .let { if (it.length > maxChars) it.take(maxChars).substringBeforeLast(' ') + "…" else it }

    /** Map SpeechRecognizer RMS dB (about -2..10) to a 0..1 meter level. */
    fun level(rmsDb: Float): Float = ((rmsDb + 2f) / 12f).coerceIn(0f, 1f)

    fun errorText(code: Int): String = when (code) {
        SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "Didn't catch that — try again."
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission is needed."
        SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Speech service network error."
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Speech service is busy."
        SpeechRecognizer.ERROR_AUDIO -> "Microphone error."
        else -> "Speech recognition error ($code)."
    }
}

/** Spoken replies (desktop SpeakWorker). One engine is kept and reused, like the desktop. */
class Speaker(context: Context) : TextToSpeech.OnInitListener {
    private val tts = TextToSpeech(context.applicationContext, this)
    @Volatile var ready = false; private set
    @Volatile var initError: String? = null; private set
    private var pending: String? = null

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            ready = true
            runCatching { tts.language = Locale.getDefault() }
            pending?.let { speak(it); pending = null }
        } else initError = "No text-to-speech engine is available."
    }

    fun speak(text: String) {
        val t = VoiceText.forSpeech(text)
        if (t.isBlank()) return
        if (!ready) { pending = t; return }
        tts.speak(t, TextToSpeech.QUEUE_FLUSH, null, "kairos-reply")
    }

    fun stop() { runCatching { tts.stop() } }
    fun isSpeaking() = ready && tts.isSpeaking
}

/** One-shot speech recognition (desktop ListenWorker, max ~15 s). */
class Listener(
    private val context: Context,
    private val onLevel: (Float) -> Unit,
    private val onPartial: (String) -> Unit,
    private val onResult: (String) -> Unit,
    private val onError: (String) -> Unit,
) {
    private var rec: SpeechRecognizer? = null

    fun available() = SpeechRecognizer.isRecognitionAvailable(context)

    fun start() {
        if (!available()) {
            onError("No speech recognition service on this device. Install one (for example a FOSS keyboard with voice input) or type instead.")
            return
        }
        stop()
        rec = SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) = onLevel(0f)
                override fun onBeginningOfSpeech() = Unit
                override fun onRmsChanged(rmsdB: Float) = onLevel(VoiceText.level(rmsdB))
                override fun onBufferReceived(buffer: ByteArray?) = Unit
                override fun onEndOfSpeech() = onLevel(0f)
                override fun onError(error: Int) { onLevel(0f); onError(VoiceText.errorText(error)) }
                override fun onResults(results: Bundle?) {
                    onLevel(0f)
                    val t = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                    if (t.isBlank()) onError(VoiceText.errorText(SpeechRecognizer.ERROR_NO_MATCH)) else onResult(t)
                }
                override fun onPartialResults(partial: Bundle?) {
                    partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let(onPartial)
                }
                override fun onEvent(eventType: Int, params: Bundle?) = Unit
            })
            startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1500L))
        }
    }

    fun stop() { rec?.run { runCatching { cancel(); destroy() } }; rec = null }
}
