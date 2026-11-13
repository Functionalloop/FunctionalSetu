package com.jansetu.app.data.local

import androidx.sqlite.db.SimpleSQLiteQuery
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/** 5.8: each filter alone and two together give the same count as a direct query. */
@RunWith(AndroidJUnit4::class)
class FiltersTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private lateinit var local: LocalDb

    private val ward2 = "00000000-0000-0000-0000-0000000000a2"
    private val booth2 = "00000000-0000-0000-0000-0000000000b2"
    private val red = "00000000-0000-0000-0000-00000000c0c1"

    @Before fun setUp() = runBlocking {
        local = LocalDb(context, DbKey(context))
        local.wipe()
        local.db.lists().upsertColorTags(listOf(ColorTagEntity(red, "red", "#E53935", "लाल", "Red", false, 1, true)))
        // 600 voters: every third one in ward 2 / booth 2; every fourth surveyed, every eighth tagged red,
        // every twelfth an influencer.
        val voters = (0 until 600).map { i ->
            val v = FakeVoters.voter(i)
            if (i % 3 == 0) v.copy(wardId = ward2, boothId = booth2) else v
        }
        local.db.voters().savePulledVoters(voters, emptyList())
        local.db.voters().savePulledSurveys(voters.filterIndexed { i, _ -> i % 4 == 0 }.mapIndexed { n, v ->
            SurveyEntity(voterId = v.id, isSurveyed = true, version = 1, colorTagId = if (n % 2 == 0) red else null,
                isInfluencer = n % 3 == 0)
        })
    }

    @After fun tearDown() = local.wipe()

    private fun app(f: VoterFilter) = runBlocking { local.db.voters().countNow(VoterQuery.count(f)) }

    private fun direct(where: String, vararg args: Any) = runBlocking {
        local.db.voters().countNow(SimpleSQLiteQuery(
            "SELECT count(*) FROM voters v LEFT JOIN surveys s ON s.voter_id = v.id WHERE $where", args,
        ))
    }

    private fun same(f: VoterFilter, where: String, vararg args: Any) {
        val expected = direct(where, *args)
        assertTrue("filter $f matches nothing; the test proves nothing", expected > 0)
        assertEquals("filter $f", expected, app(f))
    }

    @Test fun eachFilterAlone() {
        same(VoterFilter(wardId = ward2), "v.ward_id = ?", ward2)
        same(VoterFilter(boothId = booth2), "v.booth_id = ?", booth2)
        same(VoterFilter(ageMin = 40), "v.age >= 40")
        same(VoterFilter(ageMax = 30), "v.age <= 30")
        same(VoterFilter(ageMin = 30, ageMax = 50), "v.age BETWEEN 30 AND 50")
        same(VoterFilter(gender = "F"), "v.gender = 'F'")
        same(VoterFilter(colorTagId = red), "s.color_tag_id = ?", red)
        same(VoterFilter(surveyed = true), "s.is_surveyed = 1")
        same(VoterFilter(surveyed = false), "s.voter_id IS NULL OR s.is_surveyed = 0")
        same(VoterFilter(influencer = true), "s.is_influencer = 1")
    }

    @Test fun twoTogether() {
        same(VoterFilter(wardId = ward2, gender = "M"), "v.ward_id = ? AND v.gender = 'M'", ward2)
        same(VoterFilter(boothId = booth2, surveyed = true), "v.booth_id = ? AND s.is_surveyed = 1", booth2)
        same(VoterFilter(ageMin = 30, ageMax = 60, colorTagId = red), "v.age BETWEEN 30 AND 60 AND s.color_tag_id = ?", red)
        same(VoterFilter(gender = "F", surveyed = false), "v.gender = 'F' AND (s.voter_id IS NULL OR s.is_surveyed = 0)")
        same(VoterFilter(q = "patil", wardId = ward2), "v.last_name_en = 'Patil' AND v.ward_id = ?", ward2)
        same(VoterFilter(influencer = true, boothId = booth2), "s.is_influencer = 1 AND v.booth_id = ?", booth2)
    }

    @Test fun totalInTheListEqualsTheCount() = runBlocking {
        val f = VoterFilter(gender = "F", surveyed = false)
        assertEquals(app(f), local.db.voters().rowsNow(VoterQuery.list(f, 10)).first().total)
    }
}
