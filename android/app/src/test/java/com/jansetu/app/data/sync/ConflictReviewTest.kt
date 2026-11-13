package com.jansetu.app.data.sync

import com.jansetu.app.data.remote.ApiResult
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

/** 7.10: deciding several conflicts of one record. */
class ConflictReviewTest {
    private val refused = ApiResult.Err(422, "validation_error", "influencer_type_id needs is_influencer = true")

    @Test fun aRefusedFieldIsTriedAgainAfterTheOthers() = runBlocking {
        val calls = mutableListOf<String>()
        var typeKept = false
        val r = resolveAll(listOf("is_influencer", "influencer_type_id")) { id ->
            calls += id
            when {
                id == "influencer_type_id" -> { typeKept = true; ApiResult.Ok(Unit) }
                typeKept -> ApiResult.Ok(Unit)
                else -> refused
            }
        }
        assertEquals(ApiResult.Ok(Unit), r)
        assertEquals(listOf("is_influencer", "influencer_type_id", "is_influencer"), calls)
    }

    @Test fun alreadyDecidedIsFine() = runBlocking {
        val r = resolveAll(listOf("a", "b")) { id ->
            if (id == "a") ApiResult.Err(409, "conflict_resolved", "Already decided.") else ApiResult.Ok(Unit)
        }
        assertEquals(ApiResult.Ok(Unit), r)
    }

    @Test fun stopsWhenNothingMoves() = runBlocking {
        var calls = 0
        val r = resolveAll(listOf("a", "b")) { calls++; refused }
        assertEquals(refused, r)
        assertEquals(2, calls)
    }

    @Test fun offlineStopsAtOnce() = runBlocking {
        var calls = 0
        val r = resolveAll(listOf("a", "b")) { calls++; ApiResult.Offline(IOException("no network")) }
        assertTrue(r is ApiResult.Offline)
        assertEquals(1, calls)
    }

    @Test fun valuesReadLikePeopleSayThem() {
        val labels = mapOf("t1" to "Teacher")
        assertEquals("Teacher", conflictValue("profession_id", JsonPrimitive("t1"), labels))
        assertEquals("Yes", conflictValue("is_influencer", JsonPrimitive(true), labels))
        assertEquals("—", conflictValue("notes", JsonNull, labels))
        assertEquals("15.6, 73.7", conflictValue("location", buildJsonObject { put("lat", 15.6); put("lng", 73.7) }, labels))
    }
}
