package com.jansetu.app.ui.share

import com.jansetu.app.data.local.VoterEntity
import com.jansetu.app.ui.slip.SlipSettings
import com.jansetu.app.ui.slip.slipContent
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** 7.12: Share on WhatsApp, at most 5 voters. Fake data only. */
class ShareWhatsAppTest {
    private val base = VoterEntity(
        id = "v1", localBodyId = "lb", wardId = "w1", boothId = "b1", sectionId = null, partNo = 12, boothNo = null,
        serialNo = 1, epicNo = "TST0000001", firstNameMr = "फेक", middleNameMr = null, lastNameMr = "नाईक",
        firstNameEn = "Fake", middleNameEn = null, lastNameEn = "Naik", relationType = null, relativeNameMr = null,
        relativeNameEn = null, gender = "M", age = 40, ageAsOf = null, houseNo = "23", addressMr = null, addressEn = null,
        listType = "main", rollStatus = "active", deletionReason = null, isRepeatedInRoll = false,
    )
    private val voters = (1..5).map { n -> base.copy(id = "v$n", serialNo = n, epicNo = "TST000000$n") }
    private val mobiles = mapOf("v1" to "9000000001", "v2" to "9000000002", "v3" to null, "v4" to "9000000004", "v5" to "9000000005")
    private val targets = voters.map { ShareTarget(it.id, "Fake ${it.serialNo}", mobiles[it.id]) }

    @Test fun fiveTickedOneWithoutMobileOpensWhatsAppFourTimesWithTheirOwnSlips() = runBlocking {
        var ticked = emptySet<String>()
        voters.forEach { ticked = tick(ticked, it.id)!! }
        assertEquals(5, ticked.size)
        assertNull("a sixth tick is refused", tick(ticked, "v6"))

        val run = ShareRun(targets.filter { it.voterId in ticked })
        val opened = mutableListOf<Pair<String, String?>>() // mobile to the EPIC on the slip sent
        while (!run.done) {
            assertTrue(run.sendNext { t ->
                val slip = slipContent(voters.first { it.id == t.voterId }, null, SlipSettings())
                opened += t.mobile!! to slip.rows.toMap()["EPIC"]
                true
            })
        }
        assertEquals(
            listOf("9000000001" to "TST0000001", "9000000002" to "TST0000002",
                "9000000004" to "TST0000004", "9000000005" to "TST0000005"),
            opened,
        )
        assertEquals(4, run.sent)
        assertEquals(listOf("v3"), run.skipped.map { it.voterId })
        assertFalse("nothing left to open", run.sendNext { error("opened after the end") })
    }

    @Test fun untickFreesAPlace() {
        val five = voters.map { it.id }.toSet()
        val four = tick(five, "v2")!!
        assertEquals(4, four.size)
        assertEquals(setOf("v1", "v3", "v4", "v5", "v6"), tick(four, "v6"))
    }

    @Test fun noWhatsAppDoesNotMoveOn() = runBlocking {
        val run = ShareRun(targets.take(2))
        assertFalse(run.sendNext { false })
        assertEquals(0, run.sent)
        assertEquals("v1", run.current?.voterId)
    }

    @Test(expected = IllegalArgumentException::class)
    fun aRoundNeverTakesSix() {
        ShareRun(targets + ShareTarget("v6", "Fake 6", "9000000006"))
    }

    @Test fun messageFromTheSettings() {
        val s = MessageSettings.parse("""{"message_start_en":"Namaskar,","candidate_message_en":" Vote for Fake Candidate. ",
            "candidate_message_mr":"फेक","message_end_mr":"धन्यवाद","polling_date":"2027-02-14"}""")
        assertEquals("Namaskar,\n\nVote for Fake Candidate.\n\nधन्यवाद", s.defaultMessage())
        // code of conduct mode: no candidate message
        assertEquals("", MessageSettings.parse("""{"candidate_message_en":null}""").defaultMessage())
        assertEquals("", MessageSettings.parse("not json").defaultMessage())
    }
}
