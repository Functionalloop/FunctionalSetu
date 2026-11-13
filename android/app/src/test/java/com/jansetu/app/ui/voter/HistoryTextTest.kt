package com.jansetu.app.ui.voter

import com.jansetu.app.data.remote.ApiJson
import com.jansetu.app.data.remote.HistoryPage
import org.junit.Assert.assertEquals
import org.junit.Test

/** 7.6: how Information Updation entries read. Fake data only. */
class HistoryTextTest {
    private val page = ApiJson.decodeFromString(HistoryPage.serializer(), """{"next_cursor":null,"items":[
        {"at":"2026-11-13T10:00:00Z","kind":"survey","action":"update",
         "by":{"id":"u1","username":"survey1","full_name_en":"Fake Surveyor","full_name_mr":null,"role":"surveyor"},
         "changes":{"notes":{"old":"Met","new":"Called"},"color_tag_id":{"old":null,"new":"c1","new_label":"Green"},
                    "is_influencer":{"old":false,"new":true},"lat":{"old":null,"new":15.7},"lng":{"old":null,"new":73.8}}},
        {"at":"2026-11-13T09:00:00Z","kind":"visit","action":"insert","by":null,
         "changes":{"outcome":{"old":null,"new":"not_home"},"revisit_at":{"old":null,"new":"2026-11-14T04:30:00+00:00"}}},
        {"at":"2026-11-13T08:00:00Z","kind":"slip","action":"whatsapp","by":null,"changes":{}},
        {"at":"2026-11-13T07:00:00Z","kind":"family","action":"update","by":null,
         "changes":{"family_id":{"old":"k1","new":null,"old_label":"Fake Kutumb"}}},
        {"at":"2026-11-13T06:00:00Z","kind":"survey","action":"insert","by":null,"changes":{"mobile_1":{"old":null,"new":"9876543210"}}}
    ]}""")

    @Test fun titles() {
        assertEquals(
            listOf("Survey: updated", "Visit", "Voter slip shared (WhatsApp)", "Kutumb Connect: updated", "Survey: first save"),
            page.items.map { entryTitle(it) },
        )
    }

    @Test fun lines() {
        assertEquals(
            listOf("Notes: Met → Called", "Colour tag: — → Green", "Influencer: No → Yes", "Location changed"),
            changeLines(page.items[0]),
        )
        assertEquals(listOf("Result: Not home", "Come again on: 14 Nov 2026, 10:00 am"), changeLines(page.items[1]).map {
            it.replace("AM", "am") // the month / am-pm words follow the device's language
        })
        assertEquals(emptyList<String>(), changeLines(page.items[2]))
        assertEquals(listOf("Kutumb: Fake Kutumb → —"), changeLines(page.items[3]))
        assertEquals(listOf("Mobile: 9876543210"), changeLines(page.items[4]))
    }
}
