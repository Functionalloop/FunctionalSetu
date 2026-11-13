package com.jansetu.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** 7.9: an app below the minimum version is sent to Update required. */
class UpdateRequiredTest {
    private val url = "https://example.test/download/jansetu-5.apk"

    @Test fun belowTheServerMinimumMustUpdate() {
        assertEquals(UpdateRequired(5, url), updateRequired(appVersionCode = 3, serverMin = 5, workspaceMin = 1, apkUrl = url))
    }

    @Test fun belowTheWorkspaceMinimumMustUpdate() {
        assertEquals(UpdateRequired(4, null), updateRequired(appVersionCode = 3, serverMin = 1, workspaceMin = 4, apkUrl = null))
    }

    @Test fun theHigherMinimumCounts() {
        assertEquals(7, updateRequired(3, serverMin = 7, workspaceMin = 4, apkUrl = url)?.minVersionCode)
        assertEquals(7, updateRequired(3, serverMin = 4, workspaceMin = 7, apkUrl = url)?.minVersionCode)
    }

    @Test fun atOrAboveTheMinimumGoesOn() {
        assertNull(updateRequired(5, serverMin = 5, workspaceMin = 5, apkUrl = url))
        assertNull(updateRequired(6, serverMin = 5, workspaceMin = 1, apkUrl = url))
        assertNull(updateRequired(1, serverMin = 1, workspaceMin = 1, apkUrl = null)) // nothing forced
    }

    @Test fun workspaceMinimumFromThePullSettings() {
        assertEquals(3, workspaceMinVersion("""{"polling_date":null,"min_app_version_code":3}"""))
        assertEquals(1, workspaceMinVersion("""{"polling_date":null}"""))
        assertEquals(1, workspaceMinVersion(null))
        assertEquals(1, workspaceMinVersion("not json"))
    }
}
