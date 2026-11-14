package com.jansetu.app.ui.nav

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.DirectionsWalk
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.HowToVote
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
import com.jansetu.app.ui.admin.roll.MatchingScreen
import com.jansetu.app.ui.admin.roll.RemovedVotersScreen
import com.jansetu.app.ui.admin.roll.RollEditScreen
import com.jansetu.app.ui.admin.roll.RollImportScreen
import com.jansetu.app.ui.quality.DataQualityScreen
import com.jansetu.app.ui.quality.DuplicatesScreen
import com.jansetu.app.ui.quality.MobileSheetScreen
import com.jansetu.app.ui.quality.MobileSheetsScreen
import com.jansetu.app.ui.quality.QUALITY_ROLES
import com.jansetu.app.ui.reports.EXPORT_ROUTE
import com.jansetu.app.ui.reports.ExportScreen
import com.jansetu.app.ui.reports.ReportRules
import com.jansetu.app.ui.reports.ReportScreen
import com.jansetu.app.ui.reports.ReportsScreen
import com.jansetu.app.ui.reports.exportRoute
import com.jansetu.app.ui.admin.logs.ActivityLogScreen
import com.jansetu.app.ui.admin.logs.WorkerActivityScreen
import com.jansetu.app.ui.admin.logs.WorkerLocationsScreen
import com.jansetu.app.ui.admin.settings.ConstituenciesScreen
import com.jansetu.app.ui.admin.settings.ElectionScreen
import com.jansetu.app.ui.admin.settings.ListsScreen
import com.jansetu.app.ui.admin.users.AddUserScreen
import com.jansetu.app.ui.admin.users.AssignScreen
import com.jansetu.app.ui.admin.users.UserDetailScreen
import com.jansetu.app.ui.admin.users.UsersScreen
import com.jansetu.app.ui.home.HomeScreen
import com.jansetu.app.ui.birthdays.BirthdaysScreen
import com.jansetu.app.ui.home.MoreScreen
import com.jansetu.app.ui.more.AnnouncementsScreen
import com.jansetu.app.ui.more.ChangePasswordScreen
import com.jansetu.app.ui.more.HelpScreen
import com.jansetu.app.ui.more.MorePage
import com.jansetu.app.ui.more.TermsScreen
import com.jansetu.app.ui.newvoter.NewVoterFormScreen
import com.jansetu.app.ui.newvoter.NewVoterListScreen
import com.jansetu.app.ui.slip.SlipScreen
import com.jansetu.app.ui.search.SearchScreen
import com.jansetu.app.ui.share.SHARE_ROUTE
import com.jansetu.app.ui.share.ShareWhatsAppScreen
import com.jansetu.app.ui.share.shareRoute
import com.jansetu.app.ui.sync.SyncScreen
import com.jansetu.app.ui.polling.BULK_VOTED_ROUTE
import com.jansetu.app.ui.polling.BulkVotedScreen
import com.jansetu.app.ui.polling.MARK_VOTED_ROUTE
import com.jansetu.app.ui.polling.bulkVotedRoute
import com.jansetu.app.ui.polling.MarkVotedScreen
import com.jansetu.app.ui.polling.PollingDayScreen
import com.jansetu.app.ui.polling.markVotedRoute
import com.jansetu.app.ui.voter.VoterScreen
import com.jansetu.app.ui.walklist.WalkListScreen
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject

private data class Tab(val route: String, val label: String, val icon: ImageVector)

private val TABS = listOf(
    Tab("home", "Home", Icons.Default.Home),
    Tab("search", "Search", Icons.Default.Search),
    Tab("walk", "Walk list", Icons.AutoMirrored.Filled.DirectionsWalk),
    Tab("polling", "Polling day", Icons.Default.HowToVote), // approved flow (13 Nov); Sync is under More
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
                            if (tab.route == "more" && problems.isNotEmpty()) { // refused items and conflicts (More > Sync)
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
                    onBirthdays = { nav.navigate("birthdays") }, onQuality = { nav.navigate("quality") })
            }
            composable("search") {
                SearchScreen(onOpen = nav::openVoter, onShare = { nav.navigate(shareRoute(it)) }, canTag = session.canSurvey,
                    onExport = if (session.user.role in QUALITY_ROLES) { f ->
                        nav.navigate(exportRoute(ReportRules.VOTER_LIST, filter = ReportRules.apiFilter(f), search = true))
                    } else null)
            }
            composable("birthdays") { BirthdaysScreen(onBack = { nav.popBackStack() }, onOpen = nav::openVoter) }
            composable("walk") { WalkListScreen(session, onOpen = nav::openVoter) }
            composable("sync") { MorePage("Sync", onBack = { nav.popBackStack() }) { SyncScreen(onOpen = nav::openVoter) } }
            composable("polling") {
                PollingDayScreen(session, onMarkVoted = { nav.navigate(markVotedRoute(it)) },
                    onMarkMany = { nav.navigate(bulkVotedRoute(it)) })
            }
            composable(BULK_VOTED_ROUTE, arguments = listOf(navArgument("boothId") { type = NavType.StringType })) {
                BulkVotedScreen(session, onBack = { nav.popBackStack() })
            }
            composable(MARK_VOTED_ROUTE, arguments = listOf(navArgument("boothId") { type = NavType.StringType })) {
                MarkVotedScreen(session, onBack = { nav.popBackStack() })
            }
            composable("more") {
                MoreScreen(session, problems = problems.size, onPhones = { nav.navigate("users") }, onNewVoters = { nav.navigate("newvoters") },
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
            // Admin (9.6)
            composable("users") {
                UsersScreen(session, onBack = { nav.popBackStack() }, onAdd = { nav.navigate("adduser") },
                    onOpen = { nav.navigate("user/$it") })
            }
            composable("adduser") {
                AddUserScreen(session, onBack = { nav.popBackStack() },
                    onCreated = { id -> nav.navigate("user/$id") { popUpTo("users") } })
            }
            composable("user/{id}", arguments = listOf(navArgument("id") { type = NavType.StringType })) {
                UserDetailScreen(session, onBack = { nav.popBackStack() })
            }
            composable("assign") { AssignScreen(onBack = { nav.popBackStack() }) }
            // Admin (9.7)
            composable("election") { ElectionScreen(onBack = { nav.popBackStack() }) }
            composable("lists") { ListsScreen(onBack = { nav.popBackStack() }) }
            // Admin (9.8)
            composable("activity") { ActivityLogScreen(onBack = { nav.popBackStack() }) }
            composable("workeractivity") { WorkerActivityScreen(onBack = { nav.popBackStack() }) }
            composable("locations") { WorkerLocationsScreen(onBack = { nav.popBackStack() }) }
            composable("constituencies") {
                ConstituenciesScreen(onBack = { nav.popBackStack() }, onAddAdmin = { nav.navigate("adduser") })
            }
            // Data quality, Repeated voters, Mobile numbers, Matching Engine, Correct roll record (10.6; online only)
            composable("quality") {
                DataQualityScreen(onBack = { nav.popBackStack() }, onPairs = { nav.navigate("duplicates?source=$it") })
            }
            composable("duplicates?source={source}", arguments = listOf(navArgument("source") {
                type = NavType.StringType; defaultValue = ""
            })) { DuplicatesScreen(session, onBack = { nav.popBackStack() }, onOpen = nav::openVoter) }
            composable("mobiles") { MobileSheetsScreen(onBack = { nav.popBackStack() }, onOpen = { nav.navigate("mobilesheet/$it") }) }
            composable("mobilesheet/{id}", arguments = listOf(navArgument("id") { type = NavType.StringType })) {
                MobileSheetScreen(onBack = { nav.popBackStack() })
            }
            composable("matching") {
                MatchingScreen(session, onBack = { nav.popBackStack() }, onOpen = { nav.navigate("rollimport/$it") },
                    onRemoved = { nav.navigate("removed") })
            }
            composable("rollimport/{id}", arguments = listOf(navArgument("id") { type = NavType.StringType })) {
                RollImportScreen(session, onBack = { nav.popBackStack() })
            }
            composable("removed") { RemovedVotersScreen(session, onBack = { nav.popBackStack() }) }
            // Reports & charts, Print or export a list (11.3; online only)
            composable("reports") { ReportsScreen(session, onBack = { nav.popBackStack() }, onOpen = { nav.navigate(it) }) }
            composable("report/{key}", arguments = listOf(navArgument("key") { type = NavType.StringType })) {
                ReportScreen(onBack = { nav.popBackStack() }, onExport = { nav.navigate(it) })
            }
            composable(EXPORT_ROUTE, arguments = listOf(
                navArgument("kind") { type = NavType.StringType; defaultValue = ReportRules.VOTER_LIST },
                navArgument("report") { type = NavType.StringType; defaultValue = "" },
                navArgument("filter") { type = NavType.StringType; defaultValue = "" },
                navArgument("search") { type = NavType.BoolType; defaultValue = false },
            )) { ExportScreen(onBack = { nav.popBackStack() }) }
            composable("rolledit/{id}", arguments = listOf(navArgument("id") { type = NavType.StringType })) {
                // A removed voter leaves this phone with the sync: go back past its screen.
                RollEditScreen(onBack = { nav.popBackStack() },
                    onRemoved = { if (!nav.popBackStack("voter/{id}", inclusive = true)) nav.popBackStack() })
            }
            composable("voter/{id}", arguments = listOf(navArgument("id") { type = NavType.StringType })) {
                VoterScreen(session, onBack = { nav.popBackStack() }, onOpen = nav::openVoter,
                    onSlip = { nav.navigate("slip/$it") }, onShare = { nav.navigate(shareRoute(it)) },
                    onCorrect = { nav.navigate("rolledit/$it") })
            }
            composable(SHARE_ROUTE, arguments = listOf(navArgument("ids") { type = NavType.StringType })) {
                ShareWhatsAppScreen(onBack = { nav.popBackStack() })
            }
            composable("slip/{id}", arguments = listOf(navArgument("id") { type = NavType.StringType })) {
                SlipScreen(onBack = { nav.popBackStack() })
            }
        }
    }
}
