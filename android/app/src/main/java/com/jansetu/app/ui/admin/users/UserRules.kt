package com.jansetu.app.ui.admin.users

import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.remote.AdminUser
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * The rules of Users & devices, Add user and Booths & karyakartas (9.6), kept free of Android so they are
 * tested on the JVM (AdminUsersTest). The server checks all of them again (routers/users.py).
 */
object UserRules {
    private val USERNAME = Regex("^[A-Za-z0-9._-]{3,40}$")
    private val MOBILE = Regex("^[6-9][0-9]{9}$")

    /** Roles with assigned areas; an admin works in the whole constituency, a super admin everywhere. */
    val FIELD_ROLES = listOf("supervisor", "surveyor", "booth_agent")

    /** Roles the caller may give: an admin the field roles; a super admin also admin (approved flow: "Admin*"). */
    fun rolesFor(callerRole: String): List<String> =
        if (callerRole == "super_admin") FIELD_ROLES + "admin" else FIELD_ROLES

    /** May the caller change this user at all (edit, switch off, reset)? An admin: field roles only. */
    fun mayChange(callerRole: String, target: AdminUser): Boolean =
        callerRole == "super_admin" || target.role in FIELD_ROLES

    /** The first problem with an Add user form, worded for the screen, or null. */
    fun checkNew(fullName: String, username: String, mobile: String, needsConstituency: Boolean): String? = when {
        fullName.isBlank() -> "Write the full name."
        !USERNAME.matches(username.trim()) -> "User ID: 3 to 40 letters, digits, dot, dash or underscore (no spaces)."
        mobile.isNotBlank() && !MOBILE.matches(mobile.trim()) -> "Mobile: 10 digits starting with 6, 7, 8 or 9."
        needsConstituency -> "Choose the constituency."
        else -> null
    }

    fun checkEdit(fullName: String, mobile: String): String? = when {
        fullName.isBlank() -> "Write the full name."
        mobile.isNotBlank() && !MOBILE.matches(mobile.trim()) -> "Mobile: 10 digits starting with 6, 7, 8 or 9."
        else -> null
    }

    /**
     * The PATCH body: only what changed (the server changes only the keys sent; null clears).
     * Empty = nothing to save.
     */
    fun edits(u: AdminUser, fullName: String, fullNameMr: String, mobile: String, role: String): JsonObject {
        val out = LinkedHashMap<String, kotlinx.serialization.json.JsonElement>()
        fun text(v: String) = v.trim().ifBlank { null }
        if (fullName.trim() != u.fullNameEn) out["full_name_en"] = JsonPrimitive(fullName.trim())
        if (text(fullNameMr) != u.fullNameMr) out["full_name_mr"] = text(fullNameMr)?.let(::JsonPrimitive) ?: JsonNull
        if (text(mobile) != u.mobile) out["mobile"] = text(mobile)?.let(::JsonPrimitive) ?: JsonNull
        if (role != u.role) out["role"] = JsonPrimitive(role)
        return JsonObject(out)
    }

    // --- areas on this phone ---------------------------------------------------------------------------

    /** The constituency (level local_body) above an area, or the area itself; null if not on this phone. */
    fun constituencyOf(id: String, byId: Map<String, AreaEntity>): String? {
        var a = byId[id]
        var steps = 0
        while (a != null && a.level != "local_body" && steps++ < 10) a = a.parentId?.let(byId::get)
        return a?.takeIf { it.level == "local_body" }?.id
    }

    /** Wards and parts of one constituency (all of them when null), in list order. */
    fun inConstituency(areas: List<AreaEntity>, constituencyId: String?): List<AreaEntity> {
        val byId = areas.associateBy { it.id }
        return areas.filter {
            (it.level == "ward" || it.level == "booth") &&
                (constituencyId == null || constituencyOf(it.id, byId) == constituencyId)
        }
    }

    // --- Booths & karyakartas: the assignment list turned around (area -> users) -------------------

    /** Users assigned to this area itself (not through an area above it). */
    fun assignedTo(users: List<AdminUser>, areaId: String): List<AdminUser> = users.filter { areaId in it.areaIds }

    /**
     * Who can be ticked for an area of the given constituency: active users of `roles` there, plus anyone
     * already assigned to it (so they can be unticked even if their role changed since).
     */
    fun candidates(users: List<AdminUser>, areaId: String, constituencyId: String?, roles: Collection<String>): List<AdminUser> =
        users.filter {
            areaId in it.areaIds ||
                (it.isActive && it.role in roles && (constituencyId == null || it.localBodyId == constituencyId))
        }.sortedBy { it.fullNameEn.lowercase() }

    /**
     * The new full area list of every user whose list changes when exactly `chosen` (user ids) should hold
     * `areaId`: ticked users gain it, unticked users lose it, everyone else is left out of the map.
     */
    fun changes(users: List<AdminUser>, areaId: String, chosen: Set<String>): Map<String, List<String>> =
        users.mapNotNull { u ->
            val has = areaId in u.areaIds
            when {
                u.id in chosen && !has -> u.id to (u.areaIds + areaId)
                u.id !in chosen && has -> u.id to (u.areaIds - areaId)
                else -> null
            }
        }.toMap()
}
