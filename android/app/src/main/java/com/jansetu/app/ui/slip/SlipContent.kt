package com.jansetu.app.ui.slip

import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.VoterEntity
import com.jansetu.app.data.remote.ApiJson
import com.jansetu.app.ui.common.nameEn
import com.jansetu.app.ui.common.nameMr
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.time.LocalDate
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/** The parts of the workspace settings (pull `settings`) a slip uses. Candidate fields are null in code of conduct mode. */
@Serializable
data class SlipSettings(
    @SerialName("election_name_en") val electionNameEn: String? = null,
    @SerialName("election_name_mr") val electionNameMr: String? = null,
    @SerialName("polling_date") val pollingDate: String? = null,
    @SerialName("polling_start_time") val pollingStart: String? = null,
    @SerialName("polling_end_time") val pollingEnd: String? = null,
    @SerialName("candidate_name_en") val candidateEn: String? = null,
    @SerialName("candidate_name_mr") val candidateMr: String? = null,
    @SerialName("party_name_en") val partyEn: String? = null,
    @SerialName("party_name_mr") val partyMr: String? = null,
    @SerialName("contact_no") val contactNo: String? = null,
    @SerialName("feature_slips") val featureSlips: Boolean = true,
    @SerialName("slip_show_election_name") val showElection: Boolean = true,
    @SerialName("slip_show_booth_address") val showBoothAddress: Boolean = true,
    @SerialName("slip_show_candidate") val showCandidate: Boolean = true,
) {
    companion object {
        fun parse(json: String?): SlipSettings =
            json?.let { runCatching { ApiJson.decodeFromString(serializer(), it) }.getOrNull() } ?: SlipSettings()
    }
}

/** What is printed on one slip, in order. [missing] is shown on the screen, never on the slip. */
data class SlipContent(
    val header: List<String>,
    val rows: List<Pair<String, String>>,
    val footer: String?,
    val missing: List<String>,
)

private val DATE = DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH)
private val TIME = DateTimeFormatter.ofPattern("h:mm a", Locale.ENGLISH)

private fun date(iso: String?) = iso?.let { runCatching { DATE.format(LocalDate.parse(it)) }.getOrNull() }
private fun time(iso: String?) = iso?.let { runCatching { TIME.format(LocalTime.parse(it)).lowercase(Locale.ENGLISH) }.getOrNull() }

fun slipContent(v: VoterEntity, booth: AreaEntity?, s: SlipSettings): SlipContent {
    val header = buildList {
        if (s.showElection) (s.electionNameEn ?: s.electionNameMr)?.let { add(it) }
        if (s.showCandidate) {
            val candidate = listOfNotNull(s.candidateEn ?: s.candidateMr, s.partyEn ?: s.partyMr).joinToString(" · ")
            if (candidate.isNotBlank()) add(candidate)
        }
    }
    val pollingDate = date(s.pollingDate)
    val start = time(s.pollingStart)
    val end = time(s.pollingEnd)
    val pollingTime = when {
        start != null && end != null -> "$start to $end"
        start != null -> "from $start"
        end != null -> "until $end"
        else -> null
    }
    val station = booth?.let { b ->
        val name = listOfNotNull(b.number?.toString(), b.nameEn ?: b.nameMr).joinToString(". ")
        val address = (b.addressEn ?: b.addressMr)?.takeIf { s.showBoothAddress }
        listOfNotNull(name.ifBlank { null }, address).joinToString("\n")
    }
    val rows = buildList {
        add("Name" to listOfNotNull(v.nameEn(), v.nameMr()).joinToString("\n").ifBlank { "–" })
        v.epicNo?.let { add("EPIC" to it) }
        add("Part / serial" to "Part ${v.partNo} · Serial ${v.serialNo}")
        station?.takeIf { it.isNotBlank() }?.let { add("Polling station" to it) }
        pollingDate?.let { add("Polling date" to it) }
        pollingTime?.let { add("Polling time" to it) }
    }
    return SlipContent(
        header = header,
        rows = rows,
        footer = s.contactNo?.let { "Contact: $it" },
        missing = listOfNotNull(if (pollingDate == null) "polling date" else null, if (pollingTime == null) "polling time" else null),
    )
}
