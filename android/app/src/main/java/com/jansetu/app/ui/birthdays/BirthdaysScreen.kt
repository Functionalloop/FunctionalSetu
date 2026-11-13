package com.jansetu.app.ui.birthdays

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.local.BirthdayRow
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.ui.common.EmptyState
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.stateIn
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale
import javax.inject.Inject

/** One day of the Birthdays screen with its voters. */
data class BirthdayDay(val date: LocalDate, val people: List<BirthdayPerson>)
data class BirthdayPerson(val row: BirthdayRow, val turns: Int)

private val MD = DateTimeFormatter.ofPattern("MM-dd")

/** The 'MM-DD' keys that fall on [d]: 28 Feb also takes 29 Feb birthdays in a year without 29 Feb. */
fun birthdayKeys(d: LocalDate): List<String> =
    if (d.monthValue == 2 && d.dayOfMonth == 28 && !d.isLeapYear) listOf("02-28", "02-29") else listOf(MD.format(d))

/** Birthdays of the next [days] days from [today], grouped by day; days without one are left out. */
fun groupBirthdays(rows: List<BirthdayRow>, today: LocalDate, days: Int = 7): List<BirthdayDay> =
    (0 until days).map { today.plusDays(it.toLong()) }.mapNotNull { d ->
        val keys = birthdayKeys(d)
        val people = rows.filter { it.dob.length >= 10 && it.dob.substring(5, 10) in keys }
            .map { BirthdayPerson(it, d.year - it.dob.substring(0, 4).toInt()) }
        if (people.isEmpty()) null else BirthdayDay(d, people)
    }

fun dayTitle(d: LocalDate, today: LocalDate): String = when (d) {
    today -> "Today"
    today.plusDays(1) -> "Tomorrow"
    else -> DateTimeFormatter.ofPattern("EEEE, d MMM", Locale.ENGLISH).format(d)
}

fun BirthdayRow.name(): String =
    listOfNotNull(firstNameEn, middleNameEn, lastNameEn).joinToString(" ").ifBlank { null }
        ?: listOfNotNull(firstNameMr, middleNameMr, lastNameMr).joinToString(" ").ifBlank { "(no name)" }

/** Reads the phone's own database (the survey's date of birth): works offline. */
@HiltViewModel
class BirthdaysViewModel @Inject constructor(local: LocalDb) : ViewModel() {
    private val dao = local.db.voters()
    val today: LocalDate = LocalDate.now()

    val days = flow {
        val keys = (0 until DAYS).flatMap { birthdayKeys(today.plusDays(it.toLong())) }.distinct()
        emit(groupBirthdays(dao.birthdays(keys), today, DAYS))
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    private companion object { const val DAYS = 7 }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BirthdaysScreen(onBack: () -> Unit, onOpen: (String) -> Unit, vm: BirthdaysViewModel = hiltViewModel()) {
    val days by vm.days.collectAsStateWithLifecycle()
    val context = LocalContext.current
    Scaffold(topBar = {
        TopAppBar(
            title = { Text("Birthdays") },
            navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
        )
    }) { padding ->
        val list = days ?: return@Scaffold
        if (list.isEmpty()) {
            EmptyState("No birthdays in the next 7 days. Birthdays come from the date of birth in the survey.",
                Modifier.padding(padding))
            return@Scaffold
        }
        LazyColumn(Modifier.padding(padding).fillMaxSize()) {
            list.forEach { day ->
                item(key = day.date.toString()) {
                    Text("${dayTitle(day.date, vm.today)} · ${day.people.size}", style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(16.dp, 16.dp, 16.dp, 4.dp))
                }
                items(day.people, key = { day.date.toString() + it.row.id }) { p ->
                    Row(
                        Modifier.fillMaxWidth().clickable { onOpen(p.row.id) }.padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(p.row.name(), style = MaterialTheme.typography.titleMedium)
                            Text("Turns ${p.turns} · Part ${p.row.partNo} · Sr ${p.row.serialNo}",
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        p.row.mobile1?.let { m ->
                            OutlinedButton(onClick = {
                                try {
                                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://wa.me/91$m")))
                                } catch (e: ActivityNotFoundException) {
                                    Toast.makeText(context, "No app on this phone can do this.", Toast.LENGTH_SHORT).show()
                                }
                            }) { Text("WhatsApp") }
                        }
                    }
                    HorizontalDivider()
                }
            }
        }
    }
}
