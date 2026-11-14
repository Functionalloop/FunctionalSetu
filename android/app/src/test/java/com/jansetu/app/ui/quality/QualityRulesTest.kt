package com.jansetu.app.ui.quality

import com.jansetu.app.data.remote.DataQualitySummary
import com.jansetu.app.data.remote.MobileImport
import com.jansetu.app.data.remote.SyncVoter
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Data quality, Repeated voters and Mobile numbers wording (10.6). Fake data only. */
class QualityRulesTest {
    @Test fun summaryLinesInTheApprovedOrder() {
        val lines = QualityRules.lines(DataQualitySummary(voters = 872, noMobile = 412, noDob = 530, possibleDuplicates = 12,
            repeatedInRoll = 4, shifted = 9, doubtfulDead = 0))
        assertEquals(listOf("Missing mobile numbers", "Missing birth dates", "Possible duplicates", "Repeated in the roll",
            "Shifted address", "Doubtful “dead” marks"), lines.map { it.label })
        assertEquals(listOf(412, 530, 12, 4, 9, 0), lines.map { it.count })
        // only the two pair lines open a list: all pairs, and those marked repeated in the roll
        assertEquals(listOf(null, null, "", "roll_flag", null, null), lines.map { it.source })
    }

    @Test fun shareOfVoters() {
        assertEquals("47% of 872 voters", QualityRules.share(412, 872))
        assertNull(QualityRules.share(0, 0))
    }

    @Test fun aPairVoterIsToldApartByPartSerialAgeHouseAndEpic() {
        val v = SyncVoter(id = "v1", localBodyId = "lb", wardId = "w", boothId = "b", partNo = 12, serialNo = 340,
            firstNameEn = "Asha", lastNameEn = "Naik", relationType = "husband", relativeNameEn = "Ravi Naik", gender = "F",
            age = 41, houseNo = "88", epicNo = "ABC0000001")
        assertEquals("Asha Naik", QualityRules.name(v))
        assertEquals("Part 12 · Serial 340 · 41 · Female · House 88 · EPIC ABC0000001", QualityRules.voterLine(v))
        assertEquals("Husband: Ravi Naik", QualityRules.relativeLine(v))
        assertEquals("(no name)", QualityRules.name(v.copy(firstNameEn = null, lastNameEn = null)))
        assertEquals("Repeated in the roll", QualityRules.pairTitle("roll_flag"))
        assertEquals("Possible duplicates", QualityRules.pairTitle(null))
    }

    private fun sheet(status: String, error: String? = null) = MobileImport(id = "m1", status = status, matchedCount = 120,
        reviewCount = 8, notFoundCount = 3, error = error, createdAt = "2026-11-14T05:00:00Z")

    @Test fun sheetProgressInWords() {
        assertEquals("Waiting to start…", QualityRules.sheetLine(sheet("queued")))
        assertTrue(QualityRules.isWorking(sheet("running")))
        assertEquals("120 matched · 8 to review · 3 not found", QualityRules.sheetLine(sheet("done")))
        assertEquals("Failed: No row has a 10-digit mobile number.",
            QualityRules.sheetLine(sheet("failed", "No row has a 10-digit mobile number.")))
        assertTrue(QualityRules.rowOpen("needs_review"))
        assertTrue(QualityRules.rowOpen("not_found"))
        assertTrue(!QualityRules.rowOpen("matched"))
    }

    @Test fun onlyCsvOrExcelUpTo20Mb() {
        assertNull(QualityRules.sheetProblem("numbers.CSV", 1000))
        assertNull(QualityRules.sheetProblem("numbers.xlsx", null))
        assertEquals("Choose a CSV or Excel (.xlsx) file.", QualityRules.sheetProblem("numbers.pdf", 1000))
        assertEquals("Choose a CSV or Excel (.xlsx) file.", QualityRules.sheetProblem(null, 1000))
        assertEquals("The file is larger than 20 MB.", QualityRules.sheetProblem("big.csv", 20L * 1024 * 1024 + 1))
        assertEquals("The file is empty.", QualityRules.sheetProblem("empty.csv", 0))
        assertEquals("text/csv", QualityRules.mimeFor("a.csv"))
        assertTrue(QualityRules.mimeFor("a.xlsx").contains("spreadsheetml"))
    }
}
