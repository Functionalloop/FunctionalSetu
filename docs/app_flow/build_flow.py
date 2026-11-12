"""Builds the JANSETU app flow and wireframes, version 2 (client's list of 12 Nov 2026).

    python docs/app_flow/build_flow.py

Writes docs/app_flow/app_flow_v2.html and prints it to docs/app_flow_v2.pdf with Chrome or Edge
(headless). Standard library only. Every name, number and place on the screens is sample data.
"""

from __future__ import annotations

import html
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_HTML = HERE / "app_flow_v2.html"
OUT_PDF = HERE.parent / "app_flow_v2.pdf"

e = html.escape
FLAG = {None: "", "new": " fl-new", "chg": " fl-chg"}


# ---------------------------------------------------------------- screen parts
def bar(title, back=True, action=""):
    return f'<div class="bar">{"<b>‹</b>" if back else ""}<span>{e(title)}</span><i>{e(action)}</i></div>'


def tabs(items, on=0, flag=None):
    cells = "".join(f'<span class="{"on" if i == on else ""}">{e(t)}</span>' for i, t in enumerate(items))
    return f'<div class="tabs{FLAG[flag]}">{cells}</div>'


def field(label, value="", flag=None, pick=False, tall=False):
    return (f'<div class="f{FLAG[flag]}"><label>{e(label)}</label>'
            f'<div class="box{" tall" if tall else ""}">{e(value)}{"<u>▾</u>" if pick else ""}</div></div>')


def search(text, flag=None):
    return f'<div class="f{FLAG[flag]}"><div class="box srch">⌕ {e(text)}</div></div>'


def chips(label, items, on=(), flag=None):
    cells = "".join(f'<span class="{"on" if i in on else ""}">{e(t)}</span>' for i, t in enumerate(items))
    lab = f"<label>{e(label)}</label>" if label else ""
    return f'<div class="chips{FLAG[flag]}">{lab}<div>{cells}</div></div>'


def yn(label, yes=True, flag=None):
    return (f'<div class="yn{FLAG[flag]}"><span>{e(label)}</span><div><b class="{"on" if yes else ""}">Yes</b>'
            f'<b class="{"" if yes else "on"}">No</b></div></div>')


def row(title, sub="", right="", flag=None, check=None, dot=None):
    c = "" if check is None else f'<em class="cb{" on" if check else ""}"></em>'
    d = f'<em class="dot" style="background:{dot}"></em>' if dot else ""
    s = f"<small>{e(sub)}</small>" if sub else ""
    r = f"<i>{e(right)}</i>" if right else ""
    return f'<div class="r{FLAG[flag]}">{c}{d}<div><span>{e(title)}</span>{s}</div>{r}</div>'


def btn(text, outline=False, flag=None):
    return f'<div class="btn{" o" if outline else ""}{FLAG[flag]}">{e(text)}</div>'


def btns(*texts, flag=None):
    return f'<div class="btns{FLAG[flag]}">' + "".join(f"<span>{e(t)}</span>" for t in texts) + "</div>"


def stats(items, flag=None):
    return f'<div class="stats{FLAG[flag]}">' + "".join(f"<div><b>{e(n)}</b><span>{e(l)}</span></div>" for n, l in items) + "</div>"


def note(text, flag=None):
    return f'<div class="note{FLAG[flag]}">{e(text)}</div>'


def head(text, flag=None):
    return f'<div class="h{FLAG[flag]}">{e(text)}</div>'


def gone(text):
    return f'<div class="gone"><s>{e(text)}</s><i>removed</i></div>'


def text(t):
    return f'<div class="t">{e(t)}</div>'


def table(header, rows, flag=None):
    th = "".join(f"<th>{e(h)}</th>" for h in header)
    tr = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="tbl{FLAG[flag]}"><tr>{th}</tr>{tr}</table>'


def bars(items):
    return '<div class="bars">' + "".join(
        f'<div><span>{e(l)}</span><em style="width:{p}%"></em><i>{e(v)}</i></div>' for l, p, v in items) + "</div>"


def progress(pct, label):
    return f'<div class="prog"><em style="width:{pct}%"></em></div><div class="t c">{e(label)}</div>'


def nav(on):
    names = ["Home", "Search", "Walk list", "Polling day", "More"]
    return '<div class="grow"></div><div class="nav">' + "".join(
        f'<span class="{"on" if n == on else ""}">{n}</span>' for n in names) + "</div>"


def ext(title, lines):
    """The phone's own app (dialer, WhatsApp, SMS): not a JANSETU screen."""
    return f'<div class="ext"><b>{e(title)}</b>' + "".join(f"<span>{e(l)}</span>" for l in lines) + "</div>"


# ---------------------------------------------------------------- screens
S: dict[str, dict] = {}


def screen(key, name, body, status=None, was="", role="", why="", variant=False):
    """variant = a second view of a screen already counted (Report view shows eight reports)."""
    S[key] = dict(name=name, body="".join(body), status=status, was=was, role=role, why=why, variant=variant)


RED, GREEN, AMBER = "#d64545", "#2e9e5b", "#e0a100"

# -- login and setup (unchanged)
screen("login", "Login", [bar("JANSETU", back=False), text("Use the workspace code and user ID your admin gave you."),
       field("Workspace code", "naik"), field("User ID", "demo.surveyor"), field("Password", "••••••••"),
       btn("Log in"), text("Terms of use · Version 1.0")])
screen("setpw", "Set password", [bar("Set your password", back=False), text("First login: choose a new password of at least 8 characters."),
       field("New password", "••••••••"), field("New password again", "••••••••"), btn("Save password")])
screen("approval", "Device approval", [bar("Waiting for approval", back=False),
       note("This phone must be approved by your admin before it can download voter data."), text("Waiting… this screen moves on by itself."),
       btn("Check now", outline=True), btn("Log out", outline=True)])
screen("firstsync", "First download", [bar("Getting your voters", back=False), text("Keep the app open. You can continue later if it stops."),
       progress(62, "540 of 872 voters"), text("Areas ✓   Lists ✓   Voters …   Surveys")])
screen("update", "Update required", [bar("Update required", back=False), note("This version is too old. Install the new one to continue."),
       btn("Download update")])
screen("terms", "Terms of use", [bar("Terms of use"), text("The terms text given by the Company is shown here."), text("…"), text("…"), btn("I accept")])

# -- home and tabs
screen("home", "Home", [bar("Naik Management Solutions", back=False), text("Hello, Demo Surveyor · Surveyor"),
       stats([("872", "Voters"), ("214", "Surveyed"), ("180", "With mobile"), ("3", "Not sent yet")]),
       head("Shortcuts"), row("Search voters"), row("Walk list"), row("Eligible but Not Registered", "Add a person not on the roll", flag="chg"),
       row("Birthdays", "3 today"), head("Needs attention"), row("Data quality", "412 voters without a mobile"), nav("Home")],
       status="changed", why="Shortcut renamed: was “New voter”.")
screen("search", "Search", [bar("Search", back=False, action="☰ Filters"), search("Name, EPIC, house, mobile or serial"),
       chips("", ["Surname: Naik ✕", "Part 12 ✕"], on=(0, 1), flag="new"), text("38 voters"),
       row("Ramesh Vishnu Naik", "Part 12 · Serial 104 · House 23", dot=GREEN), row("Sunita Ramesh Naik", "Part 12 · Serial 105 · House 23", dot=GREEN),
       row("Prakash Naik", "Part 12 · Serial 221 · House 61", dot=AMBER), row("Asha Naik", "Part 12 · Serial 340 · House 88"),
       row("Long-press a voter to select many"), nav("Search")],
       status="changed", why="Surname search (change request): set in Filters, shown as a chip.")
screen("walk", "Walk list", [bar("Walk list", back=False), field("Part", "12 – Dhargal School", pick=True),
       note("Part note: Lane behind the temple is done. Houses 40–55 only after 5 pm.  ✎", flag="new"),
       row("House 21", "4 voters", "Visited ✓"), row("House 22", "2 voters", "Not home"),
       row("House 23", "Ramesh Naik, Sunita Naik + 2", "▾"), row("House 24", "5 voters"), row("House 25", "1 voter"), nav("Walk list")],
       status="changed", why="The part's shared note is on top. Houses still come from the roll's house numbers; a Kutumb is separate.")
screen("polling", "Polling day", [bar("Polling day", back=False), stats([("312", "Voted"), ("872", "Voters"), ("36%", "Turnout"), ("2", "Not sent yet")]),
       bars([("9 am", 22, "70"), ("11 am", 48, "151"), ("1 pm", 29, "91")]), btn("Mark voted"), btn("Mark many voted", outline=True), nav("Polling day")])
screen("more", "More", [bar("More", back=False), row("Sync & list updates"), row("Announcements"),
       row("Eligible but Not Registered list", flag="chg"), row("Mobile numbers & contacts"), row("Birthdays"),
       row("Reports", "8 new reports", flag="chg"), row("Change password"), row("Help & support"), row("Terms of use"),
       head("Admin"), row("Users & devices"), row("Booths & karyakartas"), row("Village Panchayats", flag="new"), row("Election & candidate"),
       row("Lists & labels"), row("Activity log · Worker locations"), row("Know My Constituency", "Admin and super admin", flag="new"),
       head("Super admin"), row("Matching Engine", "Admin can view", flag="new"), row("Constituencies"), row("Log out"), nav("More")],
       status="changed", why="New items: Know My Constituency, Matching Engine (its own item), Village Panchayats. Renamed: Eligible but Not Registered list.")

# -- finding voters
screen("filters", "Filters", [bar("Filters", action="Clear all"), field("Village Panchayat", "Dhargal", flag="chg", pick=True),
       field("Part / Booth", "12 – Dhargal School", pick=True), field("Surname", "Naik", flag="new"),
       chips("Age", ["From 18", "To 120"]), chips("Gender", ["Male", "Female", "Third gender"]),
       chips("Colour tag", ["Ours", "Opposite", "Doubtful"]), chips("Influencer", ["Influencers only"], flag="chg"),
       field("Influencer type", "All", flag="chg", pick=True), gone("Important voters"),
       chips("Survey", ["Surveyed", "Not surveyed"]), btn("Show 38 voters")],
       status="changed", why="Influencer filter replaces Important voters. New: Surname, Village Panchayat (was Ward).")
screen("selmany", "Select many voters", [bar("4 selected", action="Select all"),
       row("Ramesh Vishnu Naik", "Serial 104 · 98xxxxxx10", check=True), row("Sunita Ramesh Naik", "Serial 105 · 98xxxxxx11", check=True),
       row("Vishnu Naik", "Serial 106 · no mobile", check=True), row("Meera Naik", "Serial 107 · 97xxxxxx52", check=True),
       row("Prakash Naik", "Serial 221", check=False), row("Asha Naik", "Serial 340", check=False),
       head("With the selected voters"), btn("Share on WhatsApp (5 or fewer)", flag="new"), btn("Set colour tag", outline=True),
       btn("Print or export a list", outline=True)],
       status="changed", why="New action: Share on WhatsApp, offered when 5 or fewer voters are ticked.")
screen("share", "Share on WhatsApp", [bar("Share on WhatsApp"), note("At most 5 voters at a time. WhatsApp opens for each voter; you press Send each time."),
       chips("What to send", ["Voter slip", "Message"], on=(1,)), field("Message", "Namaskar. Polling is on 14 Feb, 7 am to 6 pm. Please vote.", tall=True),
       head("To (4 of 5)"), row("Ramesh Vishnu Naik", "98xxxxxx10", "✓"), row("Sunita Ramesh Naik", "98xxxxxx11", "✓"),
       row("Vishnu Naik", "No mobile number", "skipped"), row("Meera Naik", "97xxxxxx52", "✓"), btn("Open WhatsApp (3)")],
       status="new", why="The bulk option: up to 5 voters, through the phone's own WhatsApp. No WhatsApp API, no bulk SMS.")
screen("profile", "Voter profile", [bar("Ramesh Vishnu Naik"), tabs(["Details", "Survey", "Kutumb Connect", "Information Updation"], 0, flag="chg"),
       row("Father", "Vishnu Naik"), row("Age / gender", "46 · Male"), row("EPIC", "ABC1234567"), row("Part / serial", "Part 12 · Serial 104"),
       row("Village Panchayat", "Dhargal", flag="chg"), row("Booth", "12 · Govt. Primary School, Dhargal"), row("House", "23"),
       head("98xxxxxx10"), btns("Call", "WhatsApp", "SMS"), btn("Voter slip", outline=True)],
       status="changed", why="Tabs renamed: Family → Kutumb Connect, History → Information Updation. Ward → Village Panchayat. Call, WhatsApp and SMS stay.")

# -- one voter
screen("survey", "Voter survey", [bar("Ramesh Vishnu Naik"), tabs(["Details", "Survey", "Kutumb Connect", "Information Updation"], 1),
       field("Mobile 1", "98xxxxxx10"), field("Caste", "—", pick=True), field("Profession", "Farmer", pick=True),
       chips("Colour tag", ["Ours", "Opposite", "Doubtful"], on=(0,)), gone("White colour tag"), gone("Important voter + position"),
       yn("Influencer", True, flag="chg"), field("Influencer type (search)", "Panch Member", flag="chg", pick=True),
       text("Sarpanch · Panch Member · Up Sarpanch · ZP Member · Ex. ZP Member · MLA · Ex. MLA · NGO · Social Worker · News Reporter · Social Media Influencer"),
       yn("Self help group", True), field("Group name", "Shree Sateri Mahila Gat"), chips("Ration card", ["AAY", "PHH", "NPHH"], on=(1,)),
       gone("Two-wheeler · Mandal / Group"), field("Notes for this voter", "…"), row("Part note", "Shared note for Part 12", "›", flag="new"), btn("Save")],
       status="changed", why="No Important voter field. Influencer: Yes / No, then one of the 11 entries. Also on this tab: mobile 2, residence check, date of birth.")
screen("kutumb", "Kutumb Connect", [bar("Ramesh Vishnu Naik"), tabs(["Details", "Survey", "Kutumb Connect", "Information Updation"], 2),
       field("Kutumb name (typed by the surveyor)", "Ramesh Naik  ✎", flag="chg"), text("4 members · Part 12"),
       row("Ramesh Vishnu Naik", "Serial 104 · 46 M", "Remove"), row("Sunita Ramesh Naik", "Serial 105 · 41 F", "Remove"),
       row("Vishnu Naik", "Serial 106 · 74 M", "Remove"), row("Meera Naik", "Serial 107 · 22 F", "Remove"),
       btn("+ Add a member (search)", outline=True), btn("Share on WhatsApp (pick up to 5)", flag="new"), gone("Family head"),
       note("A voter with no Kutumb sees: “New Kutumb” and “Add to a Kutumb”.")],
       status="renamed", was="Family", why="Made by the surveyor: a name and its members. No family head. Not created from house numbers (please confirm, see last page).")
screen("history", "Information Updation", [bar("Ramesh Vishnu Naik"), tabs(["Details", "Survey", "Kutumb Connect", "Information Updation"], 3),
       row("12 Nov 2026, 4:10 pm · Demo Surveyor", "Mobile 1: (empty) → 98xxxxxx10"), row("12 Nov 2026, 4:10 pm · Demo Surveyor", "Colour tag: Doubtful → Ours"),
       row("12 Nov 2026, 4:12 pm · Demo Surveyor", "Kutumb: (none) → Ramesh Naik"), row("10 Nov 2026, 11:30 am · Super admin", "Roll correction · House: 22 → 23"),
       row("9 Nov 2026, 6:02 pm · Demo Supervisor", "Influencer: No → Yes (Panch Member)"), note("Every update: what changed, who changed it, date and time. Needs internet.")],
       status="renamed", was="Voter history", why="Renamed. Shows what changed (old and new value), who and when.")
screen("slip", "Voter slip", [bar("Voter slip"), note("Candidate name · party · symbol"), row("Name", "Ramesh Vishnu Naik"), row("EPIC", "ABC1234567"),
       row("Part / serial", "Part 12 · Serial 104"), row("Polling station", "Govt. Primary School, Dhargal"), row("Polling date", "14 Feb 2027"),
       row("Polling time", "7:00 am to 6:00 pm", flag="chg"), btn("Share on WhatsApp"), btn("Save as image", outline=True)],
       status="changed", why="Polling time added; it comes from Election & candidate.")
screen("partnote", "Part note", [bar("Part 12 · note"), field("Shared note for this part", "Lane behind the temple is done. Houses 40–55 only after 5 pm. Ask for Mr Gawas at house 61.", tall=True),
       text("Last edited by Demo Surveyor, 12 Nov 2026, 3:05 pm"), note("Everyone working on this part sees and edits this note. It syncs like other changes. Booth agents can read it."), btn("Save")],
       status="new", why="One shared, synced note for each part. Opens from the walk list and the Survey tab.")

# -- polling day
screen("markvoted", "Mark voted", [bar("Mark voted · Part 12"), search("Serial number or name"), row("104 · Ramesh Vishnu Naik", "", "Voted ✓"),
       row("105 · Sunita Ramesh Naik", "", "Mark"), row("106 · Vishnu Naik", "", "Mark"), row("107 · Meera Naik", "", "Voted ✓"), text("2 marks not sent yet")])
screen("markmany", "Mark many voted", [bar("Mark many voted"), field("Serial numbers", "12, 15, 18-25", tall=True), text("10 voters · 1 already marked"),
       btn("Mark 10 voted"), text("Or tick voters in the booth list")])
screen("sync", "Sync & list updates", [bar("Sync"), stats([("3", "Not sent yet"), ("0", "Conflicts")]), text("Last sync: 12 Nov 2026, 9:01 pm"), btn("Sync now"),
       head("Needs your decision"), row("Sunita Naik · survey changed by two people", "Use server copy · Send mine again"), head("List updates"),
       row("Colour tags, castes, professions, influencer list", "Up to date")])

# -- eligible but not registered, data quality
screen("enr", "Eligible but Not Registered", [bar("Eligible but Not Registered"), field("Full name", "Rohan Ramesh Naik"), field("Relative's name", "Ramesh Naik"),
       field("Date of birth", "04 Mar 2008"), chips("Gender", ["Male", "Female", "Third gender"], on=(0,)), field("Mobile", "96xxxxxx30"),
       field("Part", "12 – Dhargal School", pick=True), chips("Form 6", ["Not applied", "Applied", "Added to roll"], on=(0,)), field("Notes", "…"), btn("Save")],
       status="renamed", was="New voter", why="Renamed. “Not registered” and “New voter” are one category.")
screen("enrlist", "Eligible but Not Registered list", [bar("Eligible but Not Registered", action="+ Add"), text("14 people"),
       row("Rohan Ramesh Naik", "Part 12 · Form 6: Not applied"), row("Priya Gawas", "Part 12 · Form 6: Applied"),
       row("Sahil Parab", "Part 13 · Form 6: Added to roll"), row("Neha Shetgaonkar", "Part 13 · Form 6: Not applied")],
       status="renamed", was="New voters list", why="Renamed.")
screen("quality", "Data quality", [bar("Data quality"), row("Missing mobile numbers", "", "412"), row("Missing birth dates", "", "530"),
       row("Possible duplicates", "", "12"), row("Repeated in the roll", "", "4"), row("Shifted address", "", "9"),
       row("Doubtful “dead” marks", "", "2"), gone("Spelling fixes")],
       status="changed", why="Spelling fixes is removed.")
screen("repeated", "Repeated voters", [bar("Repeated in the roll"), row("Asha Naik · Part 12 · Serial 340", "Asha Naik · Part 13 · Serial 18"),
       btns("Same person", "Different"), row("Sahil Parab · Part 13 · Serial 77", "Sahil Parab · Part 13 · Serial 410"), btns("Same person", "Different")])
screen("mobiles", "Mobile numbers & contacts", [bar("Mobile numbers"), btn("Import a sheet of numbers", outline=True), row("Sheet 3 Nov", "120 matched · 8 to review"),
       row("Ramesh Naik → 98xxxxxx10", "Matched by EPIC", "✓"), row("S. Gawas → 97xxxxxx08", "Needs review", "?")])

# -- matching engine
screen("matching", "Matching Engine", [bar("Matching Engine"), note("Compares a new official roll with the current one. Survey data stays with each voter."),
       btn("Upload a new roll (Excel, CSV or PDF)"), head("Comparisons"), row("Roll Jan 2027 · Parts 1–51", "Compared · 14 need a decision", "›"),
       row("Roll Nov 2026 · Parts 1–51", "Applied 12 Nov 2026", "›"), note("Super admin uploads and applies. Admin can open the results but not change them. Others get “Access denied (403)”.")],
       status="renamed", was="Roll update", role="SUPER ADMIN", why="Renamed and given its own item in the More menu.")
screen("matchres", "Matching results", [bar("Roll Jan 2027 · results"), stats([("31,204", "Matched"), ("412", "New"), ("255", "Deleted"), ("188", "Changed")]),
       tabs(["New", "Deleted", "Changed", "To decide 14"], 2), row("Ramesh Vishnu Naik · Part 12", "House: 22 → 23"), row("Asha Naik · Part 12", "Age: 41 → 42"),
       row("Prakash Naik · Part 12", "Name: Prakash Naik → Prakash V. Naik"), note("Deleted voters are marked “not in current roll”, never erased. Their survey stays."),
       btn("Apply this roll"), btn("Download report (Excel · PDF · CSV)", outline=True, flag="new")],
       status="new", role="SUPER ADMIN", why="Change request: newly added, deleted and changed voters after a comparison, with a report to download.")
screen("rolledit", "Correct roll record", [bar("Correct roll record"), field("Name", "Ramesh Vishnu Naik"), field("Age", "46"), field("House", "23"),
       field("Reason", "Wrong house number in the roll"), field("Reference", "Form 8, 2 Nov 2026"), btn("Save correction"), btn("Remove voter (hide)", outline=True)],
       status="changed", role="SUPER ADMIN", why="Only the super admin may change official roll data. Others get “Access denied (403)”.")

# -- reports
screen("reports", "Reports & charts", [bar("Reports"), head("Voter reports", flag="new"), row("Surname-wise summary", flag="new"), row("Surname-wise voter list", flag="new"),
       row("AC summary", flag="new"), row("Village Panchayat summary", flag="new"), row("Part summary", flag="new"),
       row("Male / Female / Third gender count", flag="new"), row("Influencer list", flag="new"), row("Eligible but Not Registered list", flag="new"),
       head("Campaign reports"), row("Survey progress"), row("Colour tags"), row("Age and gender charts"), row("Polling-day turnout"), row("Worker activity", "Admin")],
       status="changed", why="Change request: eight new reports, each at AC, Village Panchayat and Part level.")
screen("rv_sum", "Report view", [bar("Surname-wise summary"), chips("Level", ["AC", "Village Panchayat", "Part"], on=(1,)),
       chips("Filters", ["Panchayat: Dhargal", "Gender: All", "Age: 18–120", "Influencer: All"], on=(0,)),
       table(["Surname", "Voters"], [("Naik", "412"), ("Gawas", "388"), ("Parab", "301"), ("Shetgaonkar", "256"), ("Kambli", "190"), ("Total", "3,410")]),
       text("Tap a surname for the voter list"), btn("Download (Excel · PDF · CSV)")],
       status="new", why="One screen for all eight reports: choose the level, set filters, download. Needs internet.")
screen("rv_list", "Report view · voter list", [bar("Surname: Naik · Part 12"), chips("Level", ["AC", "Village Panchayat", "Part"], on=(2,)),
       table(["Serial", "Name", "Age", "House"], [("104", "Ramesh Vishnu Naik", "46 M", "23"), ("105", "Sunita Ramesh Naik", "41 F", "23"),
                                               ("106", "Vishnu Naik", "74 M", "23"), ("221", "Prakash Naik", "52 M", "61"), ("340", "Asha Naik", "41 F", "88")]),
       text("38 voters"), btn("Download (Excel · PDF · CSV)")],
       status="new", variant=True, why="The detailed list behind a number. The same view shows the influencer list and the Eligible but Not Registered list.")
screen("rv_area", "Report view · area summary", [bar("Village Panchayat summary"), chips("Level", ["AC", "Village Panchayat", "Part"], on=(1,)),
       table(["Panchayat", "Voters", "M", "F", "TG"], [("Dhargal", "3,410", "1,690", "1,719", "1"), ("Torxem", "2,980", "1,471", "1,509", "0"),
                                                       ("Corgao", "4,120", "2,034", "2,084", "2"), ("Pernem (Municipal Council)", "5,260", "2,588", "2,671", "1")]),
       text("Also per row: surveyed, influencers, eligible but not registered"), btn("Download (Excel · PDF · CSV)")],
       status="new", variant=True, why="AC, Village Panchayat and Part summaries, with the Male / Female / Third gender count.")
screen("export", "Print or export a list", [bar("Print or export"), chips("Format", ["Excel", "PDF", "CSV"], on=(2,), flag="chg"),
       head("Columns"), row("Serial, name, age, gender", check=True), row("House, part", check=True), row("Mobile", check=False), row("Colour tag", check=False),
       btn("Make the file"), row("voters_part12.csv", "Ready · 38 rows", "Download")],
       status="changed", why="CSV added next to Excel and PDF.")
screen("workeract", "Worker activity", [bar("Worker activity"), chips("", ["Today", "7 days", "30 days"], on=(1,)),
       table(["Worker", "Surveys", "Visits", "Mobiles"], [("Demo Surveyor", "64", "80", "51"), ("A. Gawas", "48", "70", "39"), ("S. Parab", "31", "44", "20")])],
       role="ADMIN")

# -- know my constituency
screen("kmc", "Know My Constituency", [bar("Know My Constituency"), text("Pernem (AC 2)"), row("Geography", "14 panchayats and councils · 51 parts", "›"),
       row("Demographics", "31,871 voters", "›"), row("Previous elections", "MP · AC · ZP", "›"), note("Only admin and super admin see this option. Others do not have it in the menu.")],
       status="new", role="ADMIN · SUPER ADMIN", why="Change request: a new section in the More menu.")
screen("kmc_geo", "Geography", [bar("Geography"), text("By Village Panchayat / Municipal Council, then by part"), row("Dhargal", "Village Panchayat · 6 parts · 3,410 voters", "▾"),
       row("   Part 12 · Govt. Primary School, Dhargal", "872 voters"), row("   Part 13 · Panchayat Hall, Dhargal", "640 voters"),
       row("Torxem", "Village Panchayat · 5 parts · 2,980 voters", "›"), row("Corgao", "Village Panchayat · 7 parts · 4,120 voters", "›"),
       row("Pernem", "Municipal Council · 8 parts · 5,260 voters", "›")],
       status="new", role="ADMIN · SUPER ADMIN", why="Panchayats, their parts and polling stations, with voter counts.")
screen("kmc_demo", "Demographics", [bar("Demographics"), chips("Level", ["AC", "Village Panchayat", "Part"], on=(0,)),
       stats([("31,871", "Total voters"), ("15,702", "Male"), ("16,160", "Female"), ("9", "Third gender")]), head("Age"),
       bars([("18–25", 34, "3,820"), ("26–35", 58, "6,540"), ("36–50", 82, "9,260"), ("51–65", 66, "7,430"), ("65+", 43, "4,821")]),
       text("Also: surveyed, influencers, ration card and other survey counts")],
       status="new", role="ADMIN · SUPER ADMIN", why="Worked out from the roll and the survey data already in JANSETU.")
screen("kmc_elec", "Previous elections", [bar("Previous elections"), tabs(["MP", "AC", "ZP"], 1), head("AC election · 2022"),
       table(["Candidate", "Party", "Votes"], [("Candidate A", "Party X", "13,063"), ("Candidate B", "Party Y", "9,645"), ("Candidate C", "Party Z", "3,210")]),
       head("AC election · 2017"), row("3 candidates", "Tap to open", "›"), btn("+ Add an election result", outline=True),
       note("The figures are entered from the data the Company gives.")],
       status="new", role="ADMIN · SUPER ADMIN", why="Previous MP, AC and ZP election results.")

# -- more menu (everyone)
screen("announce", "Announcements", [bar("Announcements"), row("Meeting on Sunday, 10 am", "From Admin · 12 Nov", "New"), row("New roll is applied", "From Super admin · 10 Nov")])
screen("birthdays", "Birthdays", [bar("Birthdays"), head("Today · 3"), row("Sunita Ramesh Naik", "41 · Part 12", "WhatsApp"), row("Sahil Parab", "30 · Part 13", "WhatsApp"),
       head("Tomorrow · 1"), row("Asha Naik", "42 · Part 12")])
screen("help", "Help & support", [bar("Help & support"), field("What went wrong?", "…", tall=True), btn("Send to admin"), text("App version 1.0 · Last sync 9:01 pm")])

# -- admin
screen("users", "Users & devices", [bar("Users & devices", action="+ Add"), tabs(["Users 42", "Phones waiting 2"], 1), row("Demo Surveyor · Samsung M35", "Asked 12 Nov, 8:58 pm"),
       btns("Approve", "Block"), row("A. Gawas · vivo I2207", "Asked 12 Nov, 7:40 pm"), btns("Approve", "Block")], role="ADMIN")
screen("adduser", "Add user", [bar("Add user"), field("Full name", "Anil Gawas"), field("User ID", "anil.gawas"),
       chips("Role", ["Supervisor", "Surveyor", "Booth agent", "Admin*"], on=(1,)), text("* Only the super admin can add an admin."),
       note("Temporary password: shown once. The user sets a new one at first login."), btn("Create user")], role="ADMIN")
screen("assign", "Booths & karyakartas", [bar("Booths & karyakartas"), field("Village Panchayat", "Dhargal", flag="chg", pick=True),
       row("Part 12 · Dhargal School", "Demo Surveyor, A. Gawas", "Edit"), row("Part 13 · Panchayat Hall", "S. Parab", "Edit"), row("Part 14 · Community Hall", "Nobody yet", "Assign"),
       head("Supervisor of this panchayat"), row("Demo Supervisor", "", "Change")],
       status="changed", role="ADMIN", why="Supervisors are assigned Village Panchayats (was wards); surveyors and booth agents are assigned parts.")
screen("vps", "Village Panchayats", [bar("Village Panchayats", action="+ Add"), text("Pernem (AC 2) · 51 parts"), row("Dhargal", "Village Panchayat · Parts 12–17", "Edit"),
       row("Torxem", "Village Panchayat · Parts 18–22", "Edit"), row("Corgao", "Village Panchayat · Parts 23–29", "Edit"),
       row("Pernem", "Municipal Council · Parts 1–8", "Edit"), note("The first list comes from the Company. A part belongs to exactly one panchayat or council.")],
       status="new", role="ADMIN", why="Change request: the level between the constituency and the part.")
screen("consts", "Constituencies", [bar("Constituencies", action="+ Add"), row("Pernem (AC 2)", "51 parts · 31,871 voters · Admin: Demo Admin", "›"),
       text("Up to 5 constituencies in a workspace"), btn("Add admin", outline=True)], role="SUPER ADMIN")
screen("election", "Election & candidate", [bar("Election & candidate"), field("Election", "Goa Assembly 2027"), field("Polling date", "14 Feb 2027"),
       field("Polling time", "7:00 am  to  6:00 pm", flag="chg"), field("Candidate", "Candidate name"), field("Party · symbol · photo", "Party X · ⬚ · ⬚"),
       field("Message for WhatsApp", "Namaskar. Polling is on 14 Feb…", tall=True), btn("Save")],
       status="changed", role="ADMIN · SUPER ADMIN", why="Polling time added (printed on the slip). Admin and super admin can both add and edit.")
screen("lists", "Lists & labels", [bar("Lists & labels", action="+ Add"), tabs(["Castes", "Professions", "Colour tags", "Influencer"], 3, flag="chg"),
       row("Sarpanch", "", "✎"), row("Panch Member", "", "✎"), row("Up Sarpanch", "", "✎"), row("ZP Member", "", "✎"), row("Ex. ZP Member", "", "✎"),
       row("MLA", "", "✎"), row("Ex. MLA", "", "✎"), row("NGO", "", "✎"), row("Social Worker", "", "✎"), row("News Reporter", "", "✎"), row("Social Media Influencer", "", "✎")],
       status="changed", role="ADMIN", why="The influencer list with the Company's 11 entries. Colour tags: Ours, Opposite, Doubtful (no white).")
screen("audit", "Activity log", [bar("Activity log"), search("User, voter or date"), row("12 Nov, 9:01 pm · Demo Admin", "Approved phone Samsung M35"),
       row("12 Nov, 4:10 pm · Demo Surveyor", "Survey saved · Ramesh Vishnu Naik"), row("12 Nov, 3:05 pm · Demo Surveyor", "Part note changed · Part 12")], role="ADMIN")
screen("locations", "Worker locations", [bar("Worker locations"), note("Map of where surveys were saved (no live tracking)"), row("Demo Surveyor", "64 surveys · last at 4:10 pm"),
       row("A. Gawas", "48 surveys · last at 3:32 pm")], role="ADMIN")

# -- the phone's own apps
EXT = {
    "x_call": ext("The phone's own apps", ["Dialer: number filled in", "SMS app: number filled in", "WhatsApp: chat with this number", "", "JANSETU sends nothing by itself.", "No SMS gateway, no WhatsApp API."]),
    "x_wa": ext("The phone's WhatsApp", ["Opens once for each voter", "Message or slip is filled in", "The worker presses Send", "Then the next voter opens", "", "3 chats for this example"]),
}

# ---------------------------------------------------------------- pages
# (title, subtitle, [(screen key, how you get there)])
PAGES = [
    ("Login and first setup", "What a karyakarta sees the first time. Nothing changes here.",
     [("login", "Open the app"), ("setpw", "Log in the first time"), ("approval", "Save the new password"), ("firstsync", "Admin approves the phone"), ("home", "Download finished")]),
    ("Home and bottom tabs", "The bottom bar (Home · Search · Walk list · Polling day · More) is on every main screen.",
     [("home", "Home tab"), ("search", "Search tab"), ("walk", "Walk list tab"), ("polling", "Polling day tab"), ("more", "More tab")]),
    ("Finding voters", "Search, surname search, filters, selecting many voters, and opening one voter.",
     [("search", "Search tab"), ("filters", "Tap Filters"), ("selmany", "Long-press a voter"), ("share", "Share on WhatsApp"), ("profile", "Tap a voter")]),
    ("One voter", "The voter screen has four tabs: Details, Survey, Kutumb Connect, Information Updation.",
     [("profile", "Tap a voter"), ("survey", "Survey tab"), ("kutumb", "Kutumb Connect tab"), ("history", "Information Updation tab"), ("slip", "Voter slip")]),
    ("Walk list, part notes and Kutumb Connect", "House-by-house work in a part, the part's shared note, and families made by the surveyor.",
     [("walk", "Walk list tab"), ("partnote", "Tap the part note"), ("kutumb", "Tap a voter → Kutumb Connect"), ("share", "Share on WhatsApp"), ("x_wa", "Open WhatsApp")]),
    ("Communication", "One voter: call, SMS or WhatsApp from the profile. Several voters: WhatsApp to at most 5 at a time. Everything uses the phone's own apps.",
     [("profile", "One voter"), ("x_call", "Call · WhatsApp · SMS"), ("selmany", "Several voters"), ("share", "Share on WhatsApp"), ("x_wa", "Open WhatsApp")]),
    ("Polling day", "Marking who has voted, one by one or many at once. Kept as it was.",
     [("polling", "Polling day tab"), ("markvoted", "Mark voted"), ("markmany", "Mark many voted"), ("sync", "Unsent marks warning")]),
    ("Eligible but Not Registered, and data quality", "People who are not on the roll, and cleaning the voter list.",
     [("enr", "Home shortcut"), ("enrlist", "More → list"), ("quality", "Home → Needs attention"), ("repeated", "Repeated in the roll"), ("mobiles", "More → Mobile numbers")]),
    ("Matching Engine", "Comparing an old electoral roll with a new one. Its own item in the More menu.",
     [("more", "More tab"), ("matching", "Matching Engine"), ("matchres", "Open a comparison"), ("rolledit", "Fix one record"), ("history", "Survey data is kept")]),
    ("Reports (1 of 2)", "Eight new reports. Each one can be seen at AC, Village Panchayat and Part level, filtered and downloaded.",
     [("more", "More tab"), ("reports", "Reports"), ("rv_sum", "Surname-wise summary"), ("rv_list", "Tap a surname"), ("export", "Download")]),
    ("Reports (2 of 2)", "Area summaries with the gender count, and the lists.",
     [("reports", "Reports"), ("rv_area", "Village Panchayat summary"), ("rv_list", "Influencer list · Eligible list"), ("workeract", "Worker activity")]),
    ("Know My Constituency", "A new section for admin and super admin only.",
     [("more", "More tab"), ("kmc", "Know My Constituency"), ("kmc_geo", "Geography"), ("kmc_demo", "Demographics"), ("kmc_elec", "Previous elections")]),
    ("More menu (everyone)", "Everyday tools under the More tab.",
     [("more", "More tab"), ("announce", "Announcements"), ("birthdays", "Birthdays"), ("help", "Help & support"), ("terms", "Terms of use")]),
    ("Admin (1 of 2)", "Users, phones and areas.",
     [("users", "Users & devices"), ("adduser", "+ Add"), ("assign", "Booths & karyakartas"), ("vps", "Village Panchayats"), ("consts", "Constituencies")]),
    ("Admin (2 of 2)", "Election details, lists and logs. Last: the screen an old app version shows.",
     [("election", "Election & candidate"), ("lists", "Lists & labels"), ("audit", "Activity log"), ("locations", "Worker locations"), ("update", "Old app version")]),
]

NEW = ["partnote", "share", "rv_sum", "matchres", "kmc", "kmc_geo", "kmc_demo", "kmc_elec", "vps"]
RENAMED = ["kutumb", "history", "enr", "enrlist", "matching"]
CHANGED = ["survey", "filters", "search", "profile", "walk", "slip", "selmany", "home", "more", "reports", "export", "election", "lists", "assign", "quality", "rolledit"]

CONFIRM = [
    ("Kutumb Connect", "In this flow the surveyor makes each Kutumb: types a name (usually the name of the head of the family) and adds or removes members. "
                       "Nothing is created from house numbers. Your list (item 7) asks for automatic creation from the house number. Please confirm which one you want."),
    ("Bulk message", "In this flow the bulk option is WhatsApp to at most 5 voters at a time, through the phone's own WhatsApp. There is no bulk SMS and no separate bulk screen. "
                     "Please confirm that this covers items 24 and 27."),
    ("Village Panchayats", "Please send the list of parts in each Village Panchayat and in Pernem Municipal Council. The names on these screens are only samples."),
    ("Previous elections", "Please send the MP, AC and ZP election figures you want shown: which years, and whether they are for the whole constituency, per panchayat or per part."),
    ("Influencer list", "Kept exactly as you wrote it. In Goa the post is usually called “Deputy Sarpanch”; “Up Sarpanch” can be renamed under Lists & labels."),
    ("Reports on the phone", "Reports need internet. A surveyor gets them for the assigned parts, a supervisor for the assigned panchayats, an admin for the whole constituency."),
]

ROLES = [
    ("Search, profile, survey, Kutumb Connect, part notes, WhatsApp to 5", "Yes", "Yes", "Yes", "Yes", "Read"),
    ("Eligible but Not Registered", "Yes", "Yes", "Yes", "Yes", "–"),
    ("Polling day: mark voted", "Yes", "Yes", "Yes", "–", "Yes"),
    ("Reports and downloads", "All", "Constituency", "Own panchayats", "Own parts", "–"),
    ("Election & candidate (with polling time)", "Yes", "Yes", "–", "–", "–"),
    ("Know My Constituency", "Yes", "Yes", "–", "–", "–"),
    ("Matching Engine: upload, decide, apply", "Yes", "View only", "–", "–", "–"),
    ("Correct official roll data", "Yes", "403", "403", "403", "403"),
]

PORTAL = [
    ("Voter search with surname and influencer filters, voter profile, survey", "Yes", "Yes"),
    ("Kutumb Connect, part notes, Information Updation, Eligible but Not Registered", "Yes", "Yes"),
    ("Call, SMS, WhatsApp to one voter; WhatsApp to 5", "Yes", "–  (uses the phone's apps)"),
    ("Reports at three levels, Excel / PDF / CSV", "Yes", "Yes"),
    ("Matching Engine and results", "Yes", "Yes"),
    ("Know My Constituency", "Yes", "Yes"),
    ("Users, phones, Village Panchayats, election, lists", "Yes", "Yes"),
    ("Polling day", "Yes", "Turnout view"),
]

CSS = """
@page { size: A4 landscape; margin: 8mm 9mm; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Segoe UI", Inter, Arial, sans-serif; color: #1c2430; font-size: 10px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { height: 193mm; page-break-after: always; display: flex; flex-direction: column; overflow: hidden; }
.page:last-child { page-break-after: auto; }
.ph { display: flex; align-items: baseline; gap: 10px; border-bottom: 2px solid #1c2430; padding-bottom: 5px; margin-bottom: 8px; }
.ph .n { font-size: 20px; font-weight: 700; color: #2f5fd0; }
.ph h2 { margin: 0; font-size: 17px; }
.ph p { margin: 0; color: #56606e; font-size: 10.5px; flex: 1; }
.ph .lg { display: flex; gap: 8px; font-size: 8.5px; white-space: nowrap; }
.foot { margin-top: auto; padding-top: 4px; display: flex; justify-content: space-between; color: #7b8491; font-size: 8px; border-top: 1px solid #d5dae1; }
.badge { display: inline-block; font-size: 7.5px; font-weight: 700; letter-spacing: .4px; padding: 1px 5px; border-radius: 3px; color: #fff; vertical-align: 1px; }
.b-new { background: #1f8a4c; } .b-renamed { background: #7a4fc4; } .b-changed { background: #d9822b; } .b-removed { background: #c23b3b; }
.b-role { background: #fff; color: #9a4a12; border: 1px solid #d9822b; }
.flow { display: flex; gap: 13px; justify-content: center; align-items: flex-start; flex: 1; }
.cell { width: 198px; display: flex; flex-direction: column; }
.tap { align-self: flex-start; background: #ffe58a; border: 1px solid #d8b93c; border-radius: 3px; padding: 1px 6px; font-size: 8.5px; margin-bottom: 4px; }
.tap:before { content: "▸ "; color: #8a6d00; }
.nm { font-weight: 700; font-size: 11px; margin-bottom: 4px; min-height: 44px; }
.nm small { display: block; font-weight: 400; color: #7b8491; font-size: 8.5px; }
.why { margin-top: 5px; font-size: 8.6px; color: #3c4654; line-height: 1.3; }
.phone { border: 1.6px solid #2b3442; border-radius: 13px; background: #fff; overflow: hidden; font-size: 8.4px; line-height: 1.25; min-height: 300px; display: flex; flex-direction: column; }
.phone.s-new { border-color: #1f8a4c; box-shadow: 0 0 0 2px #cdeedb; } .phone.s-renamed { border-color: #7a4fc4; box-shadow: 0 0 0 2px #e4d8f7; }
.phone.s-changed { border-color: #d9822b; box-shadow: 0 0 0 2px #fbe3c8; }
.phone > div, .phone > table { margin-left: 7px; margin-right: 7px; }
.bar { margin: 0 !important; background: #eef1f5; border-bottom: 1px solid #cfd5dd; padding: 6px 8px; font-weight: 700; font-size: 9.5px; display: flex; gap: 6px; align-items: center; }
.bar span { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .bar i { font-style: normal; font-weight: 400; color: #2f5fd0; font-size: 8px; } .bar b { font-size: 12px; line-height: 8px; }
.tabs { margin: 0 !important; display: flex; border-bottom: 1px solid #cfd5dd; }
.tabs span { flex: 1; text-align: center; padding: 4px 2px; font-size: 7.6px; color: #56606e; }
.tabs span.on { color: #2f5fd0; font-weight: 700; border-bottom: 2px solid #2f5fd0; }
.t { color: #56606e; padding: 4px 0 1px; } .t.c { text-align: center; }
.h { text-transform: uppercase; letter-spacing: .5px; font-size: 7px; color: #7b8491; font-weight: 700; padding: 6px 0 1px; }
.f { padding-top: 4px; } .f label, .chips label { display: block; font-size: 7.2px; color: #7b8491; }
.box { border: 1px solid #b9c1cc; border-radius: 4px; padding: 3px 5px; min-height: 16px; position: relative; } .box.tall { min-height: 34px; } .box.srch { color: #7b8491; border-radius: 9px; }
.box u { position: absolute; right: 5px; text-decoration: none; color: #7b8491; }
.chips { padding-top: 4px; } .chips div { display: flex; flex-wrap: wrap; gap: 3px; }
.chips span { border: 1px solid #b9c1cc; border-radius: 8px; padding: 1.5px 6px; } .chips span.on { background: #2f5fd0; border-color: #2f5fd0; color: #fff; }
.yn { display: flex; justify-content: space-between; align-items: center; padding-top: 5px; } .yn div { display: flex; }
.yn b { font-weight: 400; border: 1px solid #b9c1cc; padding: 1.5px 8px; } .yn b:first-child { border-radius: 8px 0 0 8px; } .yn b:last-child { border-radius: 0 8px 8px 0; border-left: 0; }
.yn b.on { background: #2f5fd0; border-color: #2f5fd0; color: #fff; }
.r { display: flex; align-items: center; gap: 5px; padding: 3.5px 0; border-bottom: 1px solid #e6e9ee; } .r > div { flex: 1; min-width: 0; }
.r span { display: block; } .r small { display: block; color: #7b8491; font-size: 7.4px; } .r i { font-style: normal; color: #2f5fd0; font-size: 7.6px; white-space: nowrap; }
.cb { width: 8px; height: 8px; border: 1px solid #56606e; border-radius: 2px; flex: none; } .cb.on { background: #2f5fd0; border-color: #2f5fd0; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex: none; }
.btn { margin-top: 6px; background: #2f5fd0; color: #fff; text-align: center; border-radius: 9px; padding: 4.5px; font-weight: 600; }
.btn.o { background: #fff; color: #2f5fd0; border: 1px solid #2f5fd0; }
.btns { display: flex; gap: 4px; padding-top: 4px; } .btns span { flex: 1; text-align: center; border: 1px solid #2f5fd0; color: #2f5fd0; border-radius: 9px; padding: 3px 0; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; padding-top: 5px; } .stats div { border: 1px solid #d5dae1; border-radius: 5px; padding: 3px 5px; }
.stats b { display: block; font-size: 12px; } .stats span { color: #7b8491; font-size: 7.4px; }
.note { margin-top: 5px; background: #fff8dc; border: 1px solid #ecd98a; border-radius: 4px; padding: 4px 5px; color: #5b4a00; }
.gone { display: flex; justify-content: space-between; padding: 3px 0; color: #c23b3b; } .gone i { font-size: 7px; font-style: normal; border: 1px solid #c23b3b; border-radius: 3px; padding: 0 3px; }
.tbl { border-collapse: collapse; margin-top: 5px; width: calc(100% - 14px); } .tbl th { text-align: left; font-size: 7.2px; color: #7b8491; border-bottom: 1px solid #b9c1cc; padding: 2px 2px; }
.tbl td { border-bottom: 1px solid #e6e9ee; padding: 2.5px 2px; }
.bars div { display: flex; align-items: center; gap: 4px; padding-top: 3px; } .bars span { width: 30px; color: #56606e; } .bars em { height: 7px; background: #9db5ee; border-radius: 2px; }
.bars i { font-style: normal; color: #56606e; font-size: 7.4px; }
.prog { margin-top: 10px; height: 8px; background: #e6e9ee; border-radius: 4px; overflow: hidden; } .prog em { display: block; height: 100%; background: #2f5fd0; }
.grow { flex: 1; min-height: 6px; }
.nav { margin: 0 !important; display: flex; border-top: 1px solid #cfd5dd; background: #f5f7fa; } .nav span { flex: 1; text-align: center; padding: 5px 0; font-size: 7.2px; color: #56606e; }
.nav span.on { color: #2f5fd0; font-weight: 700; }
.fl-new { box-shadow: -4px 0 0 #1f8a4c; background: #f0faf4; } .fl-chg { box-shadow: -4px 0 0 #d9822b; background: #fff6ec; }
.r.fl-new, .r.fl-chg, .f.fl-new, .f.fl-chg, .chips.fl-new, .chips.fl-chg, .yn.fl-new, .yn.fl-chg, .h.fl-new { padding-left: 4px; padding-right: 3px; }
.btn.fl-new, .btn.fl-chg { background: #2f5fd0; } .btn.o.fl-new { background: #f0faf4; } .btn.o.fl-chg { background: #fff6ec; }
.tabs.fl-chg { box-shadow: none; }
.phone > :last-child:not(.nav) { margin-bottom: 8px; }
.ext { border: 1.6px dashed #7b8491; border-radius: 13px; min-height: 300px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px; color: #56606e; font-size: 9px; text-align: center; padding: 10px; }
.ext b { color: #1c2430; font-size: 10.5px; margin-bottom: 6px; }
/* cover and tables */
.cover h1 { font-size: 30px; margin: 0; } .cover .sub { font-size: 14px; color: #56606e; margin: 4px 0 12px; }
.cols { display: flex; gap: 16px; } .cols > div { flex: 1; }
.card { border: 1px solid #d5dae1; border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; } .card h3 { margin: 0 0 5px; font-size: 12px; }
.card ul { margin: 0; padding-left: 15px; } .card li { margin-bottom: 2.5px; font-size: 9.6px; line-height: 1.3; }
table.g { border-collapse: collapse; width: 100%; font-size: 9.6px; } table.g th { text-align: left; background: #eef1f5; padding: 4px 6px; border: 1px solid #d5dae1; }
table.g td { padding: 3.5px 6px; border: 1px solid #d5dae1; vertical-align: top; }
.map { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; } .map .col { border: 1px solid #d5dae1; border-radius: 6px; padding: 6px 8px; }
.map h4 { margin: 0 0 4px; font-size: 11px; color: #2f5fd0; } .map div.i { padding: 1.5px 0; font-size: 9.2px; } .map div.i.sub { padding-left: 10px; color: #3c4654; }
.setup { display: flex; gap: 6px; align-items: center; margin-bottom: 10px; font-size: 10px; } .setup span { border: 1px solid #2b3442; border-radius: 5px; padding: 3px 8px; }
"""


def badge(status):
    return {None: "", "new": '<span class="badge b-new">NEW</span>', "renamed": '<span class="badge b-renamed">RENAMED</span>',
            "changed": '<span class="badge b-changed">CHANGED</span>'}[status]


LEGEND = ('<div class="lg"><span><span class="badge b-new">NEW</span> new screen</span><span><span class="badge b-renamed">RENAMED</span></span>'
          '<span><span class="badge b-changed">CHANGED</span></span><span style="color:#c23b3b">red = removed</span>'
          '<span><span class="tap" style="margin:0">what to tap</span></span></div>')


def cell(key, tap):
    if key in EXT:
        return f'<div class="cell"><div class="tap">{e(tap)}</div><div class="nm">Not a JANSETU screen<small>the phone\'s own app</small></div>{EXT[key]}</div>'
    s = S[key]
    was = f"was “{e(s['was'])}”" if s["was"] else ""
    role = f' <span class="badge b-role">{e(s["role"])}</span>' if s["role"] else ""
    sub = f"<small>{was}</small>" if was else ""
    why = f'<div class="why">{e(s["why"])}</div>' if s["why"] else ""
    cls = f' s-{s["status"]}' if s["status"] else ""
    return (f'<div class="cell"><div class="tap">{e(tap)}</div><div class="nm">{e(s["name"])} {badge(s["status"])}{role}{sub}</div>'
            f'<div class="phone{cls}">{s["body"]}</div>{why}</div>')


def page(n, title, sub, inner, legend=True):
    return (f'<section class="page"><div class="ph"><span class="n">{n}</span><h2>{e(title)}</h2><p>{e(sub)}</p>{LEGEND if legend else ""}</div>'
            f'{inner}<div class="foot"><span>JANSETU · App flow and wireframes · version 2 · 12 Nov 2026 · All data shown is sample data</span><span>Page {n}</span></div></section>')


def names(keys):
    return "".join(f"<li><b>{e(S[k]['name'])}</b>{' (was “' + e(S[k]['was']) + '”)' if S[k]['was'] else ''}: {e(S[k]['why'])}</li>" for k in keys)


def cover():
    total = sum(not s["variant"] for s in S.values())
    inner = f"""
<div class="cover"><h1>JANSETU · App flow and wireframes</h1>
<div class="sub">Version 2 · 12 Nov 2026 · For: Naik Management Solutions Pvt Ltd · In reply to “App Flow Modifications &amp; Additional Functional Requirements”</div></div>
<div class="cols"><div>
<div class="card"><h3>What this document is</h3><ul>
<li>The Android app flow with every requirement of your list placed in it: {total} screens (42 before). Page 2 is the map; pages 3–17 show each flow with its screens and what to tap.</li>
<li>The web portal has the same features with the same permissions (page 18). Pages 18–19 list who can do what and the points we need you to confirm.</li>
<li>Items marked <b>Change request</b> on page 19 are additions to the approved SRS (version 1.1). Their time and cost are sent separately; work on them starts after your approval.</li></ul></div>
<div class="card"><h3><span class="badge b-new">NEW</span> &nbsp;{len(NEW)} new screens</h3><ul>{names(NEW)}</ul></div>
<div class="card"><h3><span class="badge b-renamed">RENAMED</span> &nbsp;{len(RENAMED)} renamed screens</h3><ul>{names(RENAMED)}</ul></div>
</div><div>
<div class="card"><h3><span class="badge b-changed">CHANGED</span> &nbsp;{len(CHANGED)} changed screens</h3><ul>{names(CHANGED)}</ul></div>
<div class="card"><h3><span class="badge b-removed">REMOVED</span></h3><ul>
<li><b>Spelling fixes</b> screen.</li><li>Survey: White colour tag, Important voter and its position, Two-wheeler, Mandal / Group.</li>
<li>Family head. The Important voters filter (the Influencer filter takes its place).</li></ul></div>
</div></div>"""
    return page(1, "Summary of changes", "", inner, legend=False)


def flow_map():
    def col(title, items):
        return f'<div class="col"><h4>{title}</h4>' + "".join(
            f'<div class="i{" sub" if t.startswith("↳") else ""}">{t}</div>' for t in items) + "</div>"
    n, r, c = '<span class="badge b-new">NEW</span>', '<span class="badge b-renamed">RENAMED</span>', '<span class="badge b-changed">CHANGED</span>'
    a, sa = '<span class="badge b-role">ADMIN</span>', '<span class="badge b-role">SUPER ADMIN</span>'
    inner = f"""
<div class="setup"><span>Login</span>→<span>Set password (first login)</span>→<span>Device approval (admin approves)</span>→<span>First download</span>→<span><b>Home</b></span>
&nbsp; Bottom bar on every main screen: Home · Search · Walk list · Polling day · More</div>
<div class="map">
{col("Home", [f"Home {c}", "↳ Sync & list updates", f"↳ Eligible but Not Registered {r}", "↳ Birthdays", f"↳ Data quality {c}", "↳ ↳ Repeated voters"])}
{col("Search tab", [f"Search (with surname) {c}", f"↳ Filters {c}", f"↳ Select many voters {c}", f"↳ ↳ Share on WhatsApp {n}", "↳ ↳ Print or export a list", f"↳ Voter profile {c}",
                    f"↳ ↳ Voter survey {c}", f"↳ ↳ Kutumb Connect {r}", f"↳ ↳ ↳ Share on WhatsApp {n}", f"↳ ↳ Information Updation {r}", f"↳ ↳ Voter slip {c}", f"↳ ↳ Correct roll record {sa}"])}
{col("Walk list tab", [f"Walk list {c}", f"↳ Part note {n}", "↳ Tap a house → its voters", "↳ ↳ Voter profile"]) }
{col("Polling day tab", ["Polling day", "↳ Mark voted", "↳ Mark many voted", "↳ Sync (unsent marks)"])}
{col("More tab", [f"More {c}", "↳ Sync · Announcements", f"↳ Eligible but Not Registered list {r}", "↳ Mobile numbers & contacts", f"↳ Reports {c}", f"↳ ↳ Report view (8 reports) {n}",
                  f"↳ ↳ Print or export (CSV) {c}", "↳ Change password · Help · Terms", f"↳ Users & devices {a}", f"↳ Booths & karyakartas {c} {a}", f"↳ Village Panchayats {n} {a}",
                  f"↳ Election & candidate {c} {a}", f"↳ Lists & labels {c} {a}", f"↳ Activity log · Worker locations {a}", f"↳ Know My Constituency {n} {a}",
                  "↳ ↳ Geography · Demographics · Previous elections", f"↳ Matching Engine {r} {sa}", f"↳ ↳ Matching results {n}", f"↳ Constituencies {sa}"])}
</div>
<div class="card" style="margin-top:10px"><h3>Area levels (Goa)</h3><ul><li><b>Assembly Constituency (AC)</b> → <b>Village Panchayat or Municipal Council</b> → <b>Part / Booth</b>.
Goa has two levels of local bodies (Village Panchayat and Zilla Panchayat) and Municipal Councils for towns, so a part belongs either to a village panchayat or to a municipal council (Pernem town).
“ZP” means Zilla Panchayat. Every report can be seen at each of the three levels.</li></ul></div>"""
    return page(2, "Map of the app", "How the screens connect. Each ↳ opens from the screen above it.", inner, legend=False)


def roles_page(n):
    rows = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in ROLES)
    prow = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in PORTAL)
    inner = f"""<div class="cols"><div style="flex:1.25"><div class="card"><h3>Who can do what</h3>
<table class="g"><tr><th>Feature</th><th>Super admin</th><th>Admin</th><th>Supervisor</th><th>Surveyor</th><th>Booth agent</th></tr>{rows}</table>
<ul style="margin-top:6px"><li>“Core staff” in your list is taken as the super admin: Know My Constituency is for admin and super admin.</li>
<li>Each person sees only the assigned area: a supervisor the assigned Village Panchayats, a surveyor or booth agent the assigned parts.</li>
<li>403 = the app and the portal answer “Access denied”.</li></ul></div></div>
<div><div class="card"><h3>Android app and web portal</h3><table class="g"><tr><th>Feature</th><th>App</th><th>Portal</th></tr>{prow}</table>
<ul style="margin-top:6px"><li>Both use the same server and the same permissions. Work saved offline on a phone reaches the portal at the next sync.</li></ul></div></div></div>"""
    return page(n, "Permissions, and app and portal", "Items 39 and 40 of your list.", inner, legend=False)


def confirm_page(n):
    rows = "".join(f"<tr><td><b>{e(a)}</b></td><td>{e(b)}</td></tr>" for a, b in CONFIRM)
    cr = [("Village Panchayat level between AC and Part", "Section 7"), ("Surname search", "Item 28"),
          ("Eight reports at three levels, with filters and Excel / PDF / CSV", "Items 29, 30 and Expected Reports"),
          ("Matching Engine: results screen and report download", "Item 35"), ("Know My Constituency", "Section 9")]
    crrows = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td></tr>" for a, b in cr)
    inner = f"""<div class="cols"><div style="flex:1.4"><div class="card"><h3>Points for you to confirm</h3><table class="g"><tr><th style="width:120px">Point</th><th>What we need</th></tr>{rows}</table></div></div>
<div><div class="card"><h3>Change requests</h3><table class="g"><tr><th>Addition to SRS version 1.1</th><th>Your list</th></tr>{crrows}</table>
<ul style="margin-top:6px"><li>All other items of your list replace or rename parts of version 1.1 and are done within it.</li>
<li>Work on the change requests starts after you approve this flow and their time and cost.</li></ul></div>
<div class="card"><h3>Approval</h3><table class="g"><tr><th></th><th>Company</th><th>Developer</th></tr>
<tr><td>Name</td><td style="width:38%">&nbsp;</td><td>Sachin Sadashiv Bhise</td></tr><tr><td>Signature and date</td><td>&nbsp;<br>&nbsp;</td><td>&nbsp;</td></tr></table></div></div></div>"""
    return page(n, "Points to confirm, and change requests", "Please reply on these with your approval.", inner, legend=False)


def build() -> str:
    used = {k for _, _, cells in PAGES for k, _ in cells if k in S}
    missing = set(S) - used
    assert not missing, f"screens not on any page: {missing}"
    assert set(NEW + RENAMED + CHANGED) == {k for k, s in S.items() if s["status"] and not s["variant"]}, "status lists do not match the screens"
    parts = [cover(), flow_map()]
    n = 3
    for title, sub, cells in PAGES:
        parts.append(page(n, title, sub, '<div class="flow">' + "".join(cell(k, t) for k, t in cells) + "</div>"))
        n += 1
    parts += [roles_page(n), confirm_page(n + 1)]
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>JANSETU · App flow and wireframes v2</title>'
            f"<style>{CSS}</style></head><body>{''.join(parts)}</body></html>")


def browser() -> str | None:
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(p).exists():
            return p
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def main() -> None:
    OUT_HTML.write_text(build(), encoding="utf-8")
    print(f"{sum(not s['variant'] for s in S.values())} screens, {len(PAGES) + 4} pages -> {OUT_HTML.name}")
    exe = browser()
    if not exe:
        sys.exit("No Chrome or Edge found: open the HTML and print it to PDF (A4 landscape, no headers).")
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()],
                   check=True, capture_output=True, timeout=120)
    print(f"-> {OUT_PDF}")


if __name__ == "__main__":
    main()
