package com.jansetu.app.data.local

import java.util.UUID
import kotlin.random.Random

/** Fake voters only (never real roll data). */
object FakeVoters {
    private val firstEn = listOf("Ramesh", "Suresh", "Sunita", "Anita", "Prakash", "Kavita", "Mahesh", "Vaishali", "Ganesh", "Rekha", "Santosh", "Pooja", "Vijay", "Meena", "Ajay", "Sneha")
    private val firstMr = listOf("रमेश", "सुरेश", "सुनीता", "अनिता", "प्रकाश", "कविता", "महेश", "वैशाली", "गणेश", "रेखा", "संतोष", "पूजा", "विजय", "मीना", "अजय", "स्नेहा")
    private val lastEn = listOf("Patil", "Naik", "Sawant", "Desai", "Gawde", "Parab", "Kambli", "Raut", "Shetye", "Gaonkar")
    private val lastMr = listOf("पाटील", "नाईक", "सावंत", "देसाई", "गावडे", "परब", "कांबळी", "राऊत", "शेट्ये", "गावकर")

    val ward = "00000000-0000-0000-0000-0000000000a1"
    val booth = "00000000-0000-0000-0000-0000000000b1"
    val localBody = "00000000-0000-0000-0000-0000000000c1"

    fun voter(i: Int, rnd: Random = Random(i)): VoterEntity {
        val f = rnd.nextInt(firstEn.size)
        val l = rnd.nextInt(lastEn.size)
        return VoterEntity(
            id = UUID.nameUUIDFromBytes("fake-$i".toByteArray()).toString(),
            localBodyId = localBody, wardId = ward, boothId = booth, sectionId = null,
            partNo = 1 + i / 1000, boothNo = 1 + i / 1000, serialNo = 1 + i % 1000,
            epicNo = "FAK%07d".format(i),
            firstNameMr = firstMr[f], middleNameMr = null, lastNameMr = lastMr[l],
            firstNameEn = firstEn[f], middleNameEn = null, lastNameEn = lastEn[l],
            relationType = "father", relativeNameMr = null, relativeNameEn = firstEn[(f + 3) % firstEn.size],
            gender = if (f % 2 == 0) "M" else "F", age = 18 + rnd.nextInt(70), ageAsOf = "2026-01-01",
            houseNo = "${1 + rnd.nextInt(400)}", addressMr = null, addressEn = "Fake Wadi",
            listType = "main", rollStatus = "active", deletionReason = null, isRepeatedInRoll = false,
        )
    }
}
