package com.jansetu.app.ui.newvoter

import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.NewVoterEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate

/** 7.5: the form refuses what the server refuses (NewVoterFields), before saving offline. */
class NewVoterFormTest {
    private val today = LocalDate.of(2026, 11, 13)
    private val ok = NewVoterForm(nameEn = "Fake Person", boothId = "b1")
    private val booth = AreaEntity("b1", "w1", "booth", "1001", 1, "बूथ", "Booth 1", null, null, null, 0)

    @Test fun rules() {
        assertNull(ok.problem(today))
        assertNull(ok.copy(nameEn = "", nameMr = "नाव").problem(today))
        assertEquals("Give the name.", ok.copy(nameEn = "  ").problem(today))
        assertEquals("Pick the part.", ok.copy(boothId = null).problem(today))
        assertEquals("Mobile: 10 digits starting with 6, 7, 8 or 9.", ok.copy(mobile = "5876543210").problem(today))
        assertNull(ok.copy(mobile = "9876543210").problem(today))
        assertEquals("Date of birth: day/month/year, for example 5/1/2008.", ok.copy(dob = "2008-01-05").problem(today))
        assertEquals("Date of birth is in the future.", ok.copy(dob = "14/11/2026").problem(today))
        assertNull(ok.copy(dob = "5/1/2008").problem(today))
    }

    @Test fun toEntityTakesTheWardFromThePartAndDropsAKutumbOfAnotherPart() {
        val e = ok.copy(dob = "5/1/2008", form6 = "applied").toEntity(null, booth)
        assertEquals("w1", e.wardId)
        assertEquals("b1", e.boothId)
        assertEquals("2008-01-05", e.dob)
        assertEquals("applied", e.form6Status)

        val saved = NewVoterEntity(id = "n1", wardId = "w0", boothId = "b0", familyId = "k0", createdAt = "x", version = 3)
        val moved = ok.toEntity(saved, booth)
        assertEquals("n1", moved.id)
        assertEquals(3, moved.version)
        assertNull("a Kutumb belongs to one part", moved.familyId)
        assertEquals("k0", ok.copy(boothId = "b0").toEntity(saved, booth.copy(id = "b0")).familyId)
    }

    @Test fun formRoundTrip() {
        val e = NewVoterEntity(id = "n1", fullNameEn = "A", dob = "2008-01-05", wardId = "w1", boothId = "b1",
            form6Status = "approved", createdAt = "x")
        val f = NewVoterForm.of(e)
        assertEquals("5/1/2008", f.dob)
        assertEquals("approved", f.form6)
        assertEquals("2008-01-05", f.toEntity(e, booth).dob)
    }
}
