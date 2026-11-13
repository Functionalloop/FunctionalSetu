package com.jansetu.app.ui.polling

import com.jansetu.app.data.local.MarkRow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BulkPlanTest {
    /** A part with serials 1-30; serial 20 is already marked. */
    private val part = (1..30).map { MarkRow("v$it", it, "Fake", null, "Voter$it", null, null, null, isVoted = it == 20, pending = false) }

    @Test fun typedSerialsMarkTenAndSkipOneAlreadyMarked() {
        val plan = planBulk("12, 15, 18-25", part)
        assertEquals(10, plan.toMark.size + plan.already)   // "10 voters"
        assertEquals(1, plan.already)                        // serial 20 is left as it is
        assertEquals(listOf(12, 15, 18, 19, 21, 22, 23, 24, 25), plan.toMark.map { it.serialNo })
        assertTrue(plan.missing.isEmpty())
    }

    @Test fun serialsNotInThePartAreListed() {
        val plan = planBulk("29 30 31-33, 40", part)
        assertEquals(listOf(29, 30), plan.toMark.map { it.serialNo })
        assertEquals("31-33, 40", serialsText(plan.missing))
    }

    @Test fun sameRulesAsTheServer() {
        assertEquals(listOf(3, 4, 5, 6, 7, 9), parseSerials("3 4  5 - 7,9").getOrThrow())
        assertEquals(listOf(1, 2), parseSerials("2, 1, 1").getOrThrow())
        listOf("0", "5-3", "a", "1-", "1,,2x", "1-2001").forEach { bad ->
            assertTrue("$bad should be refused", parseSerials(bad).isFailure)
        }
        assertNotNull(planBulk("5-3", part).error)
        assertEquals(BulkPlan(), planBulk("  ", part))
    }
}
