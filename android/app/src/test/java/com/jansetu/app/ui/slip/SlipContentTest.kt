package com.jansetu.app.ui.slip

import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.VoterEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/** 7.7: what the voter slip says. Fake data only. */
class SlipContentTest {
    private val voter = VoterEntity(
        id = "v1", localBodyId = "lb", wardId = "w1", boothId = "b1", sectionId = null, partNo = 12, boothNo = null,
        serialNo = 104, epicNo = "TST0000104", firstNameMr = "फेक", middleNameMr = null, lastNameMr = "नाईक",
        firstNameEn = "Fake", middleNameEn = null, lastNameEn = "Naik", relationType = null, relativeNameMr = null,
        relativeNameEn = null, gender = "M", age = 46, ageAsOf = null, houseNo = "23", addressMr = null, addressEn = null,
        listType = "main", rollStatus = "active", deletionReason = null, isRepeatedInRoll = false,
    )
    private val booth = AreaEntity("b1", "w1", "booth", "12", 12, "शाळा", "Govt. Primary School", null, "Main road", 2, 0)

    private val settings = SlipSettings.parse("""{"election_name_en":"Fake Election 2027","polling_date":"2027-02-14",
        "polling_start_time":"07:00:00","polling_end_time":"18:00:00","candidate_name_en":"Fake Candidate",
        "party_name_en":"Party X","contact_no":"9876543210","feature_slips":true,"slip_show_booth_address":true,
        "slip_show_candidate":true,"slip_show_election_name":true,"something_new":1}""")

    @Test fun fullSlip() {
        val c = slipContent(voter, booth, settings)
        assertEquals(listOf("Fake Election 2027", "Fake Candidate · Party X"), c.header)
        assertEquals(
            listOf(
                "Name" to "Fake Naik\nफेक नाईक",
                "EPIC" to "TST0000104",
                "Part / serial" to "Part 12 · Serial 104",
                "Polling station" to "12. Govt. Primary School\nMain road",
                "Polling date" to "14 Feb 2027",
                "Polling time" to "7:00 am to 6:00 pm",
            ),
            c.rows,
        )
        assertEquals("Contact: 9876543210", c.footer)
        assertEquals(emptyList<String>(), c.missing)
    }

    @Test fun switchesAndMissingSettings() {
        val off = settings.copy(showCandidate = false, showElection = false, showBoothAddress = false,
            pollingDate = null, pollingStart = null, pollingEnd = null)
        val c = slipContent(voter, booth, off)
        assertEquals(emptyList<String>(), c.header)
        assertEquals("12. Govt. Primary School", c.rows.toMap()["Polling station"])
        assertFalse("Polling date" in c.rows.toMap())
        assertEquals(listOf("polling date", "polling time"), c.missing)
    }

    @Test fun noSettingsYetStillGivesASlip() {
        val s = SlipSettings.parse(null)
        val c = slipContent(voter.copy(epicNo = null), null, s)
        assertEquals(listOf("Name", "Part / serial"), c.rows.map { it.first })
        assertEquals(true, s.featureSlips)
        assertEquals(SlipSettings(), SlipSettings.parse("not json"))
    }
}
