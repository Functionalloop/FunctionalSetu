package com.jansetu.app.ui.share

import com.jansetu.app.data.remote.ApiJson
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** At most 5 voters at a time (client, 12 Nov): the only multi-send; no bulk screen, no bulk SMS. */
const val SHARE_MAX = 5

/** One voter to send to; [mobile] null = no number in the survey (skipped). */
data class ShareTarget(val voterId: String, val name: String, val mobile: String?)

/** Ticks or unticks [id]; null when it would be a sixth tick (refused). */
fun tick(ticked: Set<String>, id: String): Set<String>? = when {
    id in ticked -> ticked - id
    ticked.size >= SHARE_MAX -> null
    else -> ticked + id
}

/**
 * One round: WhatsApp opens for each ticked voter with a mobile, one after another; the worker presses
 * send in WhatsApp and comes back for the next. Voters without a mobile are skipped and counted.
 */
class ShareRun(targets: List<ShareTarget>) {
    init { require(targets.size <= SHARE_MAX) { "at most $SHARE_MAX voters at a time" } }

    val toSend: List<ShareTarget> = targets.filter { it.mobile != null }
    val skipped: List<ShareTarget> = targets.filter { it.mobile == null }
    var sent = 0
        private set

    val current: ShareTarget? get() = toSend.getOrNull(sent)
    val done: Boolean get() = sent >= toSend.size

    /** Opens WhatsApp for the current voter with [open]; moves on when it opened. */
    suspend fun sendNext(open: suspend (ShareTarget) -> Boolean): Boolean {
        val t = current ?: return false
        if (!open(t)) return false
        sent++
        return true
    }
}

/** The parts of the pulled settings the message uses (candidate fields are null in code of conduct mode). */
@Serializable
data class MessageSettings(
    @SerialName("candidate_message_en") val candidateEn: String? = null,
    @SerialName("candidate_message_mr") val candidateMr: String? = null,
    @SerialName("message_start_en") val startEn: String? = null,
    @SerialName("message_start_mr") val startMr: String? = null,
    @SerialName("message_end_en") val endEn: String? = null,
    @SerialName("message_end_mr") val endMr: String? = null,
) {
    /** Start, candidate message and end, in English where set, else Marathi; empty when nothing is set. */
    fun defaultMessage(): String = listOf(startEn ?: startMr, candidateEn ?: candidateMr, endEn ?: endMr)
        .mapNotNull { it?.trim()?.ifEmpty { null } }
        .joinToString("\n\n")

    companion object {
        fun parse(json: String?): MessageSettings =
            json?.let { runCatching { ApiJson.decodeFromString(serializer(), it) }.getOrNull() } ?: MessageSettings()
    }
}
