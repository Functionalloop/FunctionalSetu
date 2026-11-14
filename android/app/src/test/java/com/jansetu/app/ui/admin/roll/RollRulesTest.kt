package com.jansetu.app.ui.admin.roll

import com.jansetu.app.data.remote.RollImport
import com.jansetu.app.data.remote.RollImportRow
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Correct roll record and Matching Engine rules (10.6). Fake data only. */
class RollRulesTest {
    private val old = RollRules.RollForm(
        firstName = "Ramesh", middleName = "Vishnu", lastName = "Naik", relationType = "father", relativeName = "Vishnu Naik",
        gender = "M", age = "46", houseNo = "22", epicNo = "ABC1234567", serialNo = "104",
    )

    private fun ok(c: RollRules.Check) = (c as RollRules.Check.Ok).fields
    private fun problem(c: RollRules.Check) = (c as RollRules.Check.Problem).message

    @Test fun onlyTheChangedFieldsAreSent() {
        val f = ok(RollRules.changes(old, old.copy(houseNo = "23", age = "47"), hasMarathiName = false))
        assertEquals(setOf("house_no", "age"), f.keys)
        assertEquals(JsonPrimitive("23"), f["house_no"])
        assertEquals(JsonPrimitive(47), f["age"])
    }

    @Test fun emptiedTextClearsTheField() {
        val f = ok(RollRules.changes(old, old.copy(middleName = "  ", age = "", relationType = null), hasMarathiName = false))
        assertEquals(JsonNull, f["middle_name_en"])
        assertEquals(JsonNull, f["age"])
        assertEquals(JsonNull, f["relation_type"])
    }

    @Test fun textIsTrimmedAndEpicUppercased() {
        val f = ok(RollRules.changes(old, old.copy(firstName = " Ramesh ", epicNo = " xyz7654321 "), hasMarathiName = false))
        assertEquals(setOf("epic_no"), f.keys) // the trimmed name is unchanged
        assertEquals(JsonPrimitive("XYZ7654321"), f["epic_no"])
    }

    @Test fun serialIsSentAsANumber() {
        assertEquals(JsonPrimitive(105), ok(RollRules.changes(old, old.copy(serialNo = "105"), false))["serial_no"])
    }

    @Test fun whatTheServerWouldRefuseIsCaughtFirst() {
        assertEquals("Nothing has changed.", problem(RollRules.changes(old, old, false)))
        assertTrue(problem(RollRules.changes(old, old.copy(age = "17"), false)).startsWith("Age"))
        assertTrue(problem(RollRules.changes(old, old.copy(age = "126"), false)).startsWith("Age"))
        assertTrue(problem(RollRules.changes(old, old.copy(serialNo = "0"), false)).startsWith("The serial"))
        assertTrue(problem(RollRules.changes(old, old.copy(serialNo = ""), false)).startsWith("The serial"))
        assertTrue(problem(RollRules.changes(old, old.copy(epicNo = "AB-12"), false)).startsWith("EPIC"))
        assertEquals("Give the voter a name.", problem(RollRules.changes(old, old.copy(firstName = "", lastName = ""), false)))
        // a Marathi name on record is enough
        assertTrue(RollRules.changes(old, old.copy(firstName = "", lastName = ""), true) is RollRules.Check.Ok)
    }

    @Test fun referenceIsTrimmedAndCut() {
        assertNull(RollRules.reference("   "))
        assertEquals(200, RollRules.reference("x".repeat(300))!!.length)
    }

    private fun row(status: String?, voter: String? = "v1", review: String = "pending") = RollImportRow(
        id = 1, rowNo = 7, matchStatus = status, matchedVoterId = voter, reviewStatus = review,
    )

    @Test fun buttonsFollowTheServerRules() {
        assertEquals(RollRules.Actions("Same voter", "Add as a new voter"), RollRules.actions(row("uncertain")))
        assertEquals(RollRules.Actions("Same voter, skip the row", "A different person: add"), RollRules.actions(row("possible_duplicate")))
        assertEquals(RollRules.Actions(null, "Skip this row"), RollRules.actions(row(null, voter = null)))
        assertEquals(RollRules.Actions(null, "Add as a new voter"), RollRules.actions(row("uncertain", voter = null)))
        // absent rows follow the matches; decided rows have no buttons
        assertEquals(RollRules.Actions(null, null), RollRules.actions(row("absent_from_current_roll")))
        assertEquals(RollRules.Actions(null, null), RollRules.actions(row("uncertain", review = "accepted")))
        assertEquals("Decided: add as new", RollRules.reviewLabel(row("uncertain", review = "rejected")))
        assertEquals("Decided: skip", RollRules.reviewLabel(row(null, voter = null, review = "rejected")))
    }

    private fun import(status: String, counts: Map<String, Int>) = RollImport(
        id = "i1", localBodyId = "lb", listType = "main", title = "Roll Jan 2027", status = status, counts = counts,
        createdAt = "2026-11-14T05:00:00Z",
    )

    @Test fun applyWaitsForEveryDecision() {
        assertFalse(RollRules.canApply(import("review", mapOf("to_review" to 3))))
        assertTrue(RollRules.canApply(import("review", mapOf("to_review" to 0))))
        assertFalse(RollRules.canApply(import("parsing", emptyMap())))
        assertEquals("Compared · 3 need a decision", RollRules.statusLine(import("review", mapOf("to_review" to 3))))
        assertTrue(RollRules.isWorking(import("uploaded", emptyMap())))
    }

    @Test fun appliedCountsShowOnlyAfterApply() {
        val counts = mapOf("rows" to 10, "matched" to 8, "new" to 2, "added" to 2, "new_pairs" to 1)
        assertEquals(listOf("Rows in the file", "Matched", "New voters"), RollRules.countLines(import("review", counts)).map { it.first })
        assertEquals(listOf("Rows in the file", "Matched", "New voters", "Voters added", "New possible duplicates"),
            RollRules.countLines(import("applied", counts)).map { it.first })
    }
}
