# JANSETU – Software Requirements Specification

Nov 12, 2026&#32;

This SRS fixes what JANSETU will deliver by 15 Dec 2026 for INR 75,000 (including GST). Once both parties approve it, anything not written here is a change request.

## Document details

| Item | Detail |
| --- | --- |
| Product | JANSETU – Citizen Connect and Constituency Development Management Platform |
| Client (Company) | Naik Management Solutions Private Limited, Sawantwadi, Maharashtra |
| Developer | Shree Samarth Krupa (Proprietor: Sachin Sadashiv Bhise), Moira, Goa |
| Version | 1.1 – approved by the Company on 12 Nov 2026; constituency limit raised to 7 on 14 Nov 2026 |
| Date | 12 Nov 2026 (updated 14 Nov 2026) |
| Attachments | Android app wireframes (43 screens; 42 are built, see "Changes in 1.1") and the screen flow PDF |

**How to use this document:** the Company reads it, marks any changes, and confirms in writing (WhatsApp or email is enough). The approved version becomes the scope for the agreement's Schedule A.

## Changes in 1.1

Version 1.1 adds the changes the Company asked for on 12 Nov 2026, and scanned roll PDFs.

- **Survey:** no white colour tag. New: important voter with position, influencer with type, self help group with group name, ration card (AAY, PHH or NPHH). Two-wheeler and mandal / group are not on the form.
- **Part notes:** one shared note for each roll part, synced to everyone working on that part.
- **Search:** an Important voters filter.
- **Family:** families are made by hand by surveyors, with a name they type. They are no longer grouped by house number.
- **WhatsApp to families:** up to 5 families at a time; the slip or the message goes to every voter in them.
- **History:** every change shows what changed, who changed it and when.
- **Voter slip:** shows the polling date and time.
- **Roles:** only the super admin changes official roll data. Admin and super admin both edit election and candidate details.
- **Spelling fixes:** removed. 42 of the 43 wireframe screens are built.
- **Scanned roll PDFs:** now included (see "Data handling").
- **Existing data:** the old app's data is not imported, by the Company's decision.
- "Not registered" means a new voter; no change.
- **Constituencies (14 Nov 2026):** up to 7 constituencies per workspace, in place of 5. Price and dates are unchanged.

## Draft for version 1.2 (not approved)

The Company sent a further list on the evening of 12 Nov 2026 (`client_changes_12nov.pdf`). The text of version 1.1 below is unchanged until the Company approves the updated app flow (`app_flow_v2.pdf`); this section says what version 1.2 will change. The full list with each decision is in `change_log.md`.

**Replaces parts of 1.1 (no extra cost):**

- **Survey:** the Important voter field and its position list are removed. Influencer: yes / no, and when yes, one of Sarpanch, Panch Member, Up Sarpanch, ZP Member, Ex. ZP Member, MLA, Ex. MLA, NGO, Social Worker, News Reporter, Social Media Influencer.
- **Search:** an Influencer filter in place of the Important voters filter.
- **Kutumb Connect** is the new name for Family. A surveyor makes each Kutumb by hand, types its name and adds or removes members. There is no family head. (The Company's list says families are made automatically from the house number; to be confirmed.)
- **WhatsApp:** to at most 5 voters at a time through the phone's own WhatsApp, in place of 5 families. No bulk message screen and no bulk SMS. (The Company's list asks for a bulk message option; to be confirmed.)
- **Names:** "Voter History" becomes "Information Updation"; "New voter" and "Not registered" become "Eligible but Not Registered"; "Roll update" becomes "Matching Engine", with its own menu item.

**Change requests (time and cost to be agreed before work starts):**

- **Area structure for Goa:** Constituency (AC) → Village Panchayat or Municipal Council → Part / Booth. The Company gives the list of parts in each panchayat.
- **Surname search** in voter search.
- **Reports** at constituency, Village Panchayat and part level: surname summary, surname list, constituency / panchayat / part summaries, male / female / third gender count, influencer list, Eligible but Not Registered list. Filters: constituency, panchayat, part, surname, gender, age range, influencer. Download as Excel, PDF or CSV. A surveyor gets reports for the assigned parts, a supervisor for the assigned panchayats, an admin for the constituency. Reports need internet.
- **Matching Engine:** a results screen (new, deleted and changed voters) and a report download.
- **Know My Constituency**, for admin and super admin only: geography by panchayat and part, demographics (totals and gender), and previous MP, AC and ZP election results from figures the Company gives.
- The app would have 51 screens in place of 42.

## Overview

JANSETU lets a campaign team keep its voter list, survey every household and track polling day from an Android phone, even without internet. Admins manage the same data from a web admin portal.

JANSETU has three parts:

1. **Android app** (Kotlin) for karyakartas, supervisors, booth agents and admins. Works offline and syncs when online.
2. **Web admin portal** for managing users, roll imports, reports and exports. Its screen designs are shared separately.
3. **Backend and database** (PostgreSQL) on one KVM 4 server, shared by the app and the portal.

Each client organisation gets its own **workspace**. Data from one workspace is never visible to another.

**Area structure:** Constituency (local body) → Taluka / Gat / Gan → Ward → Booth → Section. A voter's serial number is unique within a booth.

## Users and roles

There are five roles. Each person sees and edits only the area they are assigned to.

| Role | Area they can see | What they can do |
| --- | --- | --- |
| Super admin | All constituencies in the workspace | Add constituencies, create admins, import and correct official rolls, everything an admin can do |
| Admin | One constituency | Create users, assign wards and booths, approve phones, election and candidate details, settings, all reports. Can see roll imports and corrections but not change them |
| Supervisor | Assigned wards | Search, survey, family, walk list, confirm doubtful records, reports for their wards |
| Surveyor (karyakarta) | Assigned booths | Search, survey, notes, family, new voters, mobile numbers, slips |
| Booth agent | Assigned booths | Polling day: mark voted, turnout, slips |

- An admin creates users with a temporary password. The user must set a new password on first login.
- A new phone must be approved by the admin before it can download data.
- Detailed per-feature permissions (a custom permission matrix) are **on hold** for now. The five fixed roles above apply.

## Features

The Android app has 42 screens: the 43 in the attached wireframes without Spelling fixes. They are grouped below; the screen flow PDF shows how they connect.

| Area | Features | Who |
| --- | --- | --- |
| Login and setup | Login with workspace code, user ID and password. First-login password change. Phone approval by admin. First data download. Forced update screen. Terms of use. | All |
| Home | Today's summary, sync status, shortcuts (search, walk list, new voter, birthdays), items needing attention. Bottom bar: Home, Search, Walk list, Polling day, More. | All |
| Search and filters | Search by name (English or Marathi), EPIC, serial number, house or mobile. Filters by ward, booth, age, gender, colour tag, survey status, important voters. Select many voters at once. | All |
| Voter profile | Four tabs: Details, Survey, Family, History. Call, WhatsApp or SMS using the phone's own apps. | All |
| Survey | Mobile numbers, caste, profession, colour tag (Ours, Opposite, Doubtful), residence check, date of birth, **notes per voter** (up to 2,000 characters). Important voter: yes / no, and when yes, a position chosen from a searchable list. Influencer: yes / no, and when yes, the influencer type. Self help group: yes / no, and when yes, the group name. Ration card: AAY, PHH or NPHH. Location saved only when a survey is saved. | Surveyor and above |
| Part notes | One shared note for each roll part (up to 2,000 characters), seen and edited by everyone working on that part and synced like other changes. | Surveyor and above; booth agents can read |
| Family and walk list | Surveyors make families by hand: a family name they type, and the voters they add. House-by-house walk list for the assigned booth. Share to WhatsApp for up to 5 families at a time: the slip or a message goes to every voter in those families who has a mobile number, one by one through the phone's own WhatsApp. | All; families made by surveyor and above |
| New voters | Add a voter not on the roll ("not registered"); list of voters added by hand. | Surveyor and above |
| Polling day | Turnout by booth, mark voted one by one or many at once by serial number. | Booth agent and above |
| Voter slip | Slip with booth details and the polling date and time, shared as an image on WhatsApp. | All |
| Data quality | Missing mobiles, missing birth dates, possible duplicates, repeated in roll, shifted address, doubtful "dead" marks. | Supervisor and above |
| Roll updation | Apply a new official roll; review uncertain matches; correct, remove or restore one voter with a reason and reference. Full history kept. | Super admin (admins can see it) |
| Reports | Survey progress, colour tag counts, age and gender charts, worker activity report, print or export lists (PDF, Excel). | Supervisor and above |
| Admin | Constituencies (super admin), users and devices, add user, booth and karyakarta assignments, election and candidate details (admin and super admin), lists and labels, activity log, worker locations. | Admin / super admin |
| Other | Sync and list updates, announcements, mobile numbers and contacts, birthdays, change password, help and report a problem. | All |

**Web admin portal:** user and booth management, roll import from Excel, CSV and scanned PDF, roll matching review, reports and exports, and the public website pages. The portal screens are shared separately.

## Data handling

The official roll and the campaign's own data are kept apart, so a new roll never wipes out survey work.

- **Roll data:** name (English and Marathi), relative's name, age, gender, EPIC, house, booth, section and serial number, exactly as in the official roll.
- **Campaign data:** surveys, notes, mobile numbers, colour tags, families, visits, voted marks and slips. These stay linked to the voter when a new roll is applied.
- **Roll updation:** each new roll is matched to the old one. Clear matches update automatically; uncertain ones wait for the super admin. A voter missing from the new roll is marked "not in current roll", never automatically "dead".
- **Scanned roll PDFs:** the election office's roll PDFs are page images with no text. JANSETU reads them automatically on its own server or computers, with free tools and without sending voter data to any outside service. It reads PDFs in the election office's standard English layout. Every row is checked (EPIC format, age, serial numbers, the voter count on the summary page); rows that fail a check go to a review list for a person to correct, and nothing unreadable is imported without review. Accuracy is measured against the 51 roll parts already typed for AC 2 and reported to the Company; no fixed accuracy figure is promised, because it depends on the scan quality. Marathi roll PDFs are added once the Company gives sample files and a checked list to compare against; they give Marathi names only.
- **Corrections:** the super admin can correct, remove or restore one voter, with a reason and a reference. Removing only hides the voter; nothing is erased.
- **History:** every change to a voter (survey, notes, family, visits, voted marks, roll correction) is kept with what changed (old and new value), who changed it and when, and is shown in the voter's History tab.
- **Existing data:** the official roll for AC 2 (51 parts) is imported. The voter data from the current app is not imported, by the Company's decision.
- **Data ownership:** all voter and campaign data belongs to the Company.

## Platform, hosting and security

Everything runs on one KVM 4 server with no paid outside services.

| Topic | Decision |
| --- | --- |
| Android | Android 8.0 or newer. Installed as an APK downloaded from the JANSETU server, not from the Play Store. |
| Server | KVM 4 VPS (4 vCPU, 16 GB RAM, 200 GB NVMe, 16 TB monthly bandwidth), Ubuntu Server LTS, India region. Year-one hosting is included in the price. |
| Login | Workspace code + user ID + password. No OTP, so no SMS cost. |
| Offline use | Each phone keeps an encrypted copy of only its assigned area. Search, surveys and voted marks work without internet. Logging out deletes that copy; the next login downloads it again. |
| Sync | Changes upload when the phone is online; updates from others download on sync. If two people edit the same voter, the conflict is kept for review, not lost. |
| Calls and messages | Uses the phone's own dialer, WhatsApp and SMS apps. No WhatsApp Business or SMS gateway. |
| Location | Saved only when a survey or visit is saved. No live tracking. |
| Security | Encrypted connection (HTTPS), hashed passwords, one workspace's data never visible to another, phone approval, admin can block a lost phone. |
| Backups | Daily automatic database backup, kept 14 days, stored separately from the main data. Restore is tested before final delivery. |

## Limits and quality

JANSETU is sized for one workspace within these limits, on the KVM 4 server.

- **Users:** up to 200 users per workspace.
- **Constituencies:** up to 7 per workspace.
- **Languages:** voter names shown in English and Marathi. App labels in English (Marathi labels can be added as a change request).
- **Search speed:** results appear while typing on the phone, also when offline.
- **Polling day:** the server is tested for all 200 users syncing at the same time.
- **Support:** bug fixes free for 90 days after final delivery, as in the agreement.

## Not included

These items are not part of the INR 75,000 price. Any of them can be quoted separately as a change request.

- Play Store publishing. If the Company wants it, the Company creates and pays for its own Google Play account.
- OTP login, SMS gateway, WhatsApp Business API or any other paid outside service.
- iPhone (iOS) app.
- Automatic English-to-Marathi name conversion.
- More than 7 constituencies in one workspace, or a server larger than the KVM 4 (for example, 10–11 constituencies with 30–35 lakh voters).
- Hosting and domain costs from year two; the Company pays these directly.

## Milestones and acceptance

Final delivery is on 15 Dec 2026, with a demo on 25 Nov and a working build on 30 Nov.

| Date | Milestone | What the Company receives |
| --- | --- | --- |
| 11 Nov 2026 | SRS | This document and the wireframes, for approval |
| 25 Nov 2026 | Demo | Login, search, voter profile, survey and sync working on a test phone with sample or imported data |
| 30 Nov 2026 | Working build | All 42 screens working; APK for testing by the Company's team |
| 15 Dec 2026 | Final delivery | Fixes from testing, scanned roll PDF import (English), live server, backups running, admin training and handover notes |

Payments follow the agreement: INR 30,000 / 15,000 / 30,000 (40% / 20% / 40%), at the milestones in Schedule C.

**Acceptance:** at each milestone the Company tests the build and reports problems in writing within 3 working days. Problems that go against this SRS are fixed free. If nothing is reported in that time, the milestone counts as accepted.

**Change requests:** a new feature, or a change to an approved screen, is a change request. The Developer replies with the effect on time and cost, and work starts only after the Company agrees. Delays caused by late data, late feedback or late payment move the dates by the same number of days.

## Points for the Company to confirm

Please answer these with your review; they affect the build.

- [x] Colour tag names: Ours, Opposite, Doubtful (the white tag is removed).
- [x] Survey fields: changed as listed in "Changes in 1.1".

## Approval

Attachments: Android app wireframes (43 screens; 42 built) and the JANSETU screen flow PDF.

|  | Company | Developer |
| --- | --- | --- |
| Name |  | Sachin Sadashiv Bhise |
| For | Naik Management Solutions Pvt Ltd | Shree Samarth Krupa |
| Signature |  |  |
| Date |  |  |
