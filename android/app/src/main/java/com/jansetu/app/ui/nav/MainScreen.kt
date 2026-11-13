package com.jansetu.app.ui.nav

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.DirectionsWalk
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.jansetu.app.data.Session
import com.jansetu.app.data.UpdateChecker
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.sync.SyncKeys
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import com.jansetu.app.ui.admin.PhonesScreen
import com.jansetu.app.ui.home.HomeScreen
import com.jansetu.app.ui.birthdays.BirthdaysScreen
import com.jansetu.app.ui.home.MoreScreen
import com.jansetu.app.ui.more.AnnouncementsScreen
import com.jansetu.app.ui.more.ChangePasswordScreen
import com.jansetu.app.ui.more.HelpScreen
import com.jansetu.app.ui.more.TermsScreen
import com.jansetu.app.ui.newvoter.NewVoterFormScreen
import com.jansetu.app.ui.newvoter.NewVoterListScreen
import com.jansetu.app.ui.slip.SlipScreen
import com.jansetu.app.ui.search.SearchScreen
import com.jansetu.app.ui.sync.SyncScreen
import com.jansetu.app.ui.voter.VoterScreen
import com.jansetu.app.ui.walklist.WalkListScreen
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject

private data class Tab(val route: String, val label: String, val icon: ImageVector)

private val TABS = listOf(
    Tab("home", "Home", Icons.Default.Home),
    Tab("search", "Search", Icons.Default.Search),
    Tab("walk", "Walk list", Icons.AutoMirrored.Filled.DirectionsWalk),
    Tab("sync", "Sync", Icons.Default.Sync),
    Tab("more", "More", Icons.Default.Menu),
)

@HiltViewModel
class MainViewModel @Inject constructor(local: LocalDb, updates: UpdateChecker) : ViewModel() {
    val problems = local.db.outbox().problems()

    init { // the workspace's minimum app version comes with the pull settings (7.9)
        viewModelScope.launch { local.db.syncState().flow(SyncKeys.SETTINGS).collect { updates.noteSettings(it) } }
    }
}

fun NavHostController.openVoter(id: String) = navigate("voter/$id")

@Composable
fun MainScreen(session: Session, vm: MainViewModel = hiltViewModel()) {
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val current = entry?.destination?.route
    val problems by vm.problems.collectAsStateWithLifecycle(emptyList())

    Scaffold(
        bottomBar = {
            if (TABS.any { it.route == current }) NavigationBar {
                TABS.forEach { tab ->
                    NavigationBarItem(
                        selected = current == tab.route,
                        onClick = {
                            nav.navigate(tab.route) {
                                popUpTo(nav.graph.findStartDestination().id) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = {
                            if (tab.route == "sync" && problems.isNotEmpty()) {
                                BadgedBox(badge = { Badge { Text("${problems.size}") } }) { Icon(tab.icon, null) }
                            } else Icon(tab.icon, null)
                        },
                        label = { Text(tab.label) },
                    )
                }
            }
        },
    ) { padding ->
        NavHost(nav, startDestination = "home", modifier = Modifier.padding(padding)) {
            composable("home") {
                HomeScreen(session, onSearch = { nav.navigate("search") { launchSingleTop = true } },
                    onSync = { nav.navigate("sync") }, onNewVoters = { nav.navigate("newvoters") },
                    onBirthdays = { nav.navigate("birthdays") })
            }
            composable("search") { SearchScreen(onOpen = nav::openVoter, canTag = session.canSurvey) }
            composable("birthdays") { BirthdaysScreen(onBack = { nav.popBackStack() }, onOpen = nav::openVoter) }
            composable("walk") { WalkListScreen(session, onOpen = nav::openVoter) }
            composable("sync") { SyncScreen(onOpen = nav::openVoter) }
            composable("more") {
                MoreScreen(session, onPhones = { nav.navigate("phones") }, onNewVoters = { nav.navigate("newvoters") },
                    onBirthdays = { nav.navigate("birthdays") }, onOpen = { nav.navigate(it) })
            }
            composable("announcements") { AnnouncementsScreen(onBack = { nav.popBackStack() }) }
            composable("terms") { TermsScreen(onBack = { nav.popBackStack() }) }
            composable("help") { HelpScreen(onBack = { nav.popBackStack() }) }
            composable("password") { ChangePasswordScreen(onBack = { nav.popBackStack() }) }
            composable("newvoters") {
                NewVoterListScreen(onBack = { nav.popBackStack() }, onOpen = { nav.navigate("newvoter/$it") },
                    onAdd = { nav.navigate("newvoter/new") })
            }
            composable("newvoter/{id}", arguments = listOf(navArgument("id") { type = NavType.StringType })) {
                NewVoterFormScreen(session, onBack = { nav.popBackStack() })
            }
            composable("phones") { PhonesScreen(session, onBack = { nav.popBackStack() }) }
            composable("voter/{id}", arguments = listOf(navArgument("id") { type = NavType.StringType })) {
                VoterScreen(session, onBack = { nav.popBackStack() }, onOpen = nav::openVoter,
                    onSlip = { nav.navigate("slip/$it") })
            }
            composable("slip/{id}", arguments = listOf(navArgument("id") { type = NavType.StringType })) {
                SlipScreen(onBack = { nav.popBackStack() })
            }
        }
    }
}
