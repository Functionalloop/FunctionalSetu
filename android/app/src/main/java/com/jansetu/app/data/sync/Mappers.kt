package com.jansetu.app.data.sync

import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.ColorTagEntity
import com.jansetu.app.data.local.CustomFieldLabelEntity
import com.jansetu.app.data.local.ListEntryEntity
import com.jansetu.app.data.local.SurveyEntity
import com.jansetu.app.data.local.VoterEntity
import com.jansetu.app.data.remote.ColorTagDto
import com.jansetu.app.data.remote.CustomFieldLabelDto
import com.jansetu.app.data.remote.NamedListEntry
import com.jansetu.app.data.remote.SurveyDto
import com.jansetu.app.data.remote.SyncArea
import com.jansetu.app.data.remote.SyncVoter

fun SyncArea.toEntity() = AreaEntity(id, parentId, level, code, number, nameMr, nameEn, addressMr, addressEn, acNo, sortOrder)

fun SyncVoter.toEntity() = VoterEntity(
    id = id, localBodyId = localBodyId, wardId = wardId, boothId = boothId, sectionId = sectionId,
    partNo = partNo, boothNo = boothNo, serialNo = serialNo, epicNo = epicNo,
    firstNameMr = firstNameMr, middleNameMr = middleNameMr, lastNameMr = lastNameMr,
    firstNameEn = firstNameEn, middleNameEn = middleNameEn, lastNameEn = lastNameEn,
    relationType = relationType, relativeNameMr = relativeNameMr, relativeNameEn = relativeNameEn,
    gender = gender, age = age, ageAsOf = ageAsOf, houseNo = houseNo, addressMr = addressMr, addressEn = addressEn,
    listType = listType, rollStatus = rollStatus, deletionReason = deletionReason, isRepeatedInRoll = isRepeatedInRoll,
)

fun SurveyDto.toEntity() = SurveyEntity(
    voterId = voterId, mobile1 = mobile1, mobile2 = mobile2, dob = dob, casteId = casteId,
    professionId = professionId, colorTagId = colorTagId, hasNewAddress = hasNewAddress,
    newAddressMr = newAddressMr, newAddressEn = newAddressEn, notes = notes,
    extraCheck1 = extraCheck1, extraCheck2 = extraCheck2, extraInfo1 = extraInfo1, extraInfo2 = extraInfo2,
    extraInfo3 = extraInfo3, extraInfo4 = extraInfo4, extraInfo5 = extraInfo5,
    isImportant = isImportant, positionId = positionId, isInfluencer = isInfluencer,
    influencerTypeId = influencerTypeId, inSelfHelpGroup = inSelfHelpGroup, selfHelpGroupName = selfHelpGroupName,
    rationCard = rationCard,
    version = version, isSurveyed = isSurveyed, surveyedAt = surveyedAt, lat = lat, lng = lng,
    locationAccuracyM = locationAccuracyM, locationCapturedAt = locationCapturedAt, updatedAt = updatedAt,
)

fun NamedListEntry.toEntity(kind: String) = ListEntryEntity(id, kind, nameMr, nameEn, sortOrder, isActive)

fun ColorTagDto.toEntity() = ColorTagEntity(id, code, hex, labelMr, labelEn, isDefault, sortOrder, isActive)

fun CustomFieldLabelDto.toEntity() = CustomFieldLabelEntity(fieldKey, labelMr, labelEn, isEnabled)
