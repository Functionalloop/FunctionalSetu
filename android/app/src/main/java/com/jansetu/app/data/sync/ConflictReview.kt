package com.jansetu.app.data.sync

import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.ui.voter.valueText
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive

const val KEEP_PHONE = "kept_client"
const val KEEP_SERVER = "kept_server"

/**
 * Resolves every conflict id with [call]. One field can depend on another (an influencer type needs
 * "influencer" = yes), so ids refused with 422 are tried again after the others went through; it
 * stops when a round makes no progress. 409 conflict_resolved = someone already decided it: fine.
 */
suspend fun resolveAll(ids: List<String>, call: suspend (String) -> ApiResult<*>): ApiResult<Unit> {
    var left = ids
    while (left.isNotEmpty()) {
        val refused = mutableListOf<String>()
        var lastRefusal: ApiResult.Err? = null
        for (id in left) {
            when (val r = call(id)) {
                is ApiResult.Ok -> Unit
                is ApiResult.Offline -> return r
                is ApiResult.Err -> when {
                    r.status == 409 && r.code == "conflict_resolved" -> Unit
                    r.status == 422 -> { refused += id; lastRefusal = r }
                    else -> return r
                }
            }
        }
        if (refused.size == left.size) return lastRefusal!!
        left = refused
    }
    return ApiResult.Ok(Unit)
}

/** A conflict value as people read it: list ids by their names, a location as "lat, lng". */
fun conflictValue(field: String, value: JsonElement?, labels: Map<String, String>): String {
    if (field == "location" && value is JsonObject) {
        return listOfNotNull(value["lat"], value["lng"]).joinToString(", ") { it.jsonPrimitive.content }
    }
    val id = (value as? JsonPrimitive)?.takeIf { it.isString }?.content
    return valueText(field, value, id?.let { labels[it] })
}
