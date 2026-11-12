package com.jansetu.app.ui.voter

import com.jansetu.app.data.local.SurveyEntity
import com.jansetu.app.data.surveyPushData
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** 5.16: the client's survey fields of 12 Nov, from the form to the push item. */
class SurveyFormTest {
    private val stored = SurveyEntity(
        voterId = "v1", isImportant = true, positionId = "pos-1", isInfluencer = true, influencerTypeId = "inf-1",
        inSelfHelpGroup = true, selfHelpGroupName = "Fake Gat", rationCard = "PHH", extraInfo1 = "kept",
    )

    @Test fun formReadsTheStoredCopy() {
        val f = SurveyForm.of(stored)
        assertEquals(true, f.isImportant)
        assertEquals("pos-1", f.positionId)
        assertEquals("inf-1", f.influencerTypeId)
        assertEquals("Fake Gat", f.selfHelpGroupName)
        assertEquals("PHH", f.rationCard)
    }

    @Test fun switchingImportantOffClearsThePositionInTheSavedItem() {
        val f = SurveyForm.of(stored).copy(isImportant = false)
        val saved = f.applyTo(stored)
        assertEquals(false, saved.isImportant)
        assertNull(saved.positionId)

        val data = surveyPushData(saved, null)
        assertEquals("false", data["is_important"]!!.jsonPrimitive.content)
        assertEquals(JsonNull, data["position_id"])
    }

    @Test fun eachDetailGoesOnlyWithItsYes() {
        val saved = SurveyForm.of(stored).copy(isInfluencer = false, inSelfHelpGroup = false).applyTo(stored)
        assertNull(saved.influencerTypeId)
        assertNull(saved.selfHelpGroupName)
        // Even if a stale row still held them, the push data never sends a detail without its yes.
        val data = surveyPushData(stored.copy(isImportant = false, isInfluencer = false, inSelfHelpGroup = false), null)
        assertEquals(JsonNull, data["position_id"])
        assertEquals(JsonNull, data["influencer_type_id"])
        assertEquals(JsonNull, data["self_help_group_name"])
    }

    @Test fun keptValuesAndRationCardGoInThePushData() {
        val saved = SurveyForm.of(stored).applyTo(stored)
        val data = surveyPushData(saved, null)
        assertEquals("pos-1", data["position_id"]!!.jsonPrimitive.content)
        assertEquals("inf-1", data["influencer_type_id"]!!.jsonPrimitive.content)
        assertEquals("Fake Gat", data["self_help_group_name"]!!.jsonPrimitive.content)
        assertEquals("PHH", data["ration_card"]!!.jsonPrimitive.content)
        // Fields the form does not show (custom fields) are kept, because the server replaces them all.
        assertEquals("kept", data["extra_info_1"]!!.jsonPrimitive.content)
        assertTrue("location only when taken at this save", "location" !in data)
    }

    @Test fun rationCardCanBeCleared() {
        val saved = SurveyForm.of(stored).copy(rationCard = null).applyTo(stored)
        assertEquals(JsonNull, surveyPushData(saved, null)["ration_card"])
    }

    @Test fun longGroupNameIsAnError() {
        val f = SurveyForm(inSelfHelpGroup = true, selfHelpGroupName = "x".repeat(201))
        assertTrue(f.error()!!.contains("group name"))
        assertNull(SurveyForm(inSelfHelpGroup = false, selfHelpGroupName = "x".repeat(201)).error())
    }
}
