package com.jansetu.app.ui.birthdays

import com.jansetu.app.data.local.BirthdayRow
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate

/** 7.8: the Birthdays screen's days. Fake data only. */
class BirthdaysTest {
    private fun row(id: String, dob: String) = BirthdayRow(id, 1, 1, "Fake", null, id, null, null, null, dob, null)

    private val rows = listOf(
        row("a", "1980-11-13"), row("b", "1995-11-14"), row("c", "1970-12-31"),
        row("d", "2001-01-02"), row("e", "1984-02-29"), row("f", "1990-06-15"),
    )

    @Test fun nextSevenDaysOverTheYearEnd() {
        val days = groupBirthdays(rows, LocalDate.of(2026, 12, 27))
        assertEquals(listOf(LocalDate.of(2026, 12, 31), LocalDate.of(2027, 1, 2)), days.map { it.date })
        assertEquals(listOf(56), days[0].people.map { it.turns })
        assertEquals(listOf(26), days[1].people.map { it.turns })
    }

    @Test fun todayAndTomorrow() {
        val today = LocalDate.of(2026, 11, 13)
        val days = groupBirthdays(rows, today)
        assertEquals(listOf("a", "b"), days.flatMap { d -> d.people.map { it.row.id } })
        assertEquals("Today", dayTitle(days[0].date, today))
        assertEquals("Tomorrow", dayTitle(days[1].date, today))
        assertEquals("Monday, 16 Nov", dayTitle(LocalDate.of(2026, 11, 16), today))
    }

    @Test fun leapDayBirthdayShowsOn28FebruaryInOtherYears() {
        assertEquals(listOf("02-28", "02-29"), birthdayKeys(LocalDate.of(2027, 2, 28)))
        assertEquals(listOf("02-28"), birthdayKeys(LocalDate.of(2028, 2, 28)))
        assertEquals(listOf("e"), groupBirthdays(rows, LocalDate.of(2027, 2, 28), days = 1).single().people.map { it.row.id })
        assertEquals(listOf("e"), groupBirthdays(rows, LocalDate.of(2028, 2, 29), days = 1).single().people.map { it.row.id })
        assertEquals(emptyList<BirthdayDay>(), groupBirthdays(rows, LocalDate.of(2028, 2, 28), days = 1))
    }
}
