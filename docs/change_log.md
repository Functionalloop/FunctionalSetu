# JANSETU – change log

Every change the client asked for after the SRS, and what was decided. Newest list first. The tasks are in `docs/plan.md`.

- **Same** = already in SRS 1.1 (approved 12 Nov); nothing new.
- **Replaces** = takes the place of an earlier note or of something already built.
- **Change request** = not in SRS 1.1. Built only after the client approves the updated app flow; time and cost are agreed separately (SRS, "Change requests").

## 13 Nov 2026: server provider (developer's change)

Not asked by the client. SRS 1.1 ("Platform, hosting and security") says a KVM 4 VPS with 200 GB NVMe in an India region; the server is now a Bluehost VPS. The SRS text is not edited; the client must be told and should agree in writing.

| SRS 1.1 | Now | Status |
|---|---|---|
| KVM 4, 4 vCPU, 16 GB RAM | Bluehost VPS, 4 vCPU, 16 GB DDR5 | Same size |
| 200 GB NVMe | 100 GB NVMe | Less. Enough for AC 2 (database and 14 nightly dumps are a few GB); tight only for the 10–11 constituency case the SRS already puts out of scope |
| India region | No India region offered | **Tell the client:** voter data is stored outside India, and the phones are a little slower to sync (more distance). Ask them to confirm |
| Ubuntu Server LTS | Ubuntu 24.04 LTS | Same |
| Year-one hosting in the price | Monthly, ₹1,504 | Billing between developer and client to be confirmed |
| – | SSH key "FunctionalServer" only, no password login | Same as plan 6.4 |

## 12 Nov 2026 (evening): client's final list

Source: `docs/client_changes_12nov.pdf` ("App Flow Modifications & Additional Functional Requirements", 40 items), with the developer's answers of 12 Nov. It replaces the earlier notes of the same day wherever they differ. The client wants an updated app flow to approve before development goes on: `docs/app_flow_v2.pdf`.

| PDF item | What the client asked | Status | Decision | Tasks |
|---|---|---|---|---|
| 1 | No white colour tag | Same | Built (5.14, 5.16) | – |
| 1 (Influencer), 2 | Influencer yes / no, and when yes a searchable list: Sarpanch, Panch Member, Up Sarpanch, ZP Member, Ex. ZP Member, MLA, Ex. MLA, NGO, Social Worker, News Reporter, Social Media Influencer. No separate Important voter field | Replaces | The Important voter field and the positions list (built 12 Nov) are taken out. The influencer list gets these 11 entries; an admin can still edit the list | 7.13 |
| 3 | No Two-wheeler, no Mandal / Group | Same | Never built | – |
| 3 (Self help group) | Self help group yes / no with a group name | Same | Built | – |
| 4 | Ration card AAY, PHH, NPHH | Same | Built | – |
| 5 | Synced notes for the whole part | Same | One shared note per part | 7.11 |
| 6 | Filter for influencers | Replaces | The Important voters filter becomes an Influencer filter | 7.13 |
| 7, 8 | Families made automatically from the house number, then edited | Replaces (developer's decision, 12 Nov) | **Not automatic.** The surveyor makes each Kutumb, types its name (usually the name of the head of the family, as plain text) and adds or removes members. This differs from PDF item 7; the app flow asks the client to confirm it | 7.1, 7.2, 7.4 |
| 9 | No family head | Replaces | No head field; "set the head" leaves the contract | 7.1 |
| 10 | "Family" becomes "Kutumb Connect" | Replaces | Tab, screen and menu names | 7.4 |
| 11 | No WhatsApp API; a standard share | Same | The phone's own WhatsApp | 7.12 |
| 12, 13 | History of every update: what, who, when | Same | – | 7.6 |
| 14, 17 | Polling time on the voter slip | Same | – | 7.7, 9.4 |
| 15 | "Voter History" becomes "Information Updation" | Replaces | Tab and screen name | 7.6 |
| 16 | Admin and super admin edit elections and candidates | Same | – | 9.4 |
| 18 | Keep polling day | Same | – | Step 8 |
| 19 | Remove Spelling fixes | Same | Done in the contract (5.15) | – |
| 20, 21 | Only the super admin edits official roll data; others get 403 | Same | Done in the contract (5.15) | Step 10 |
| 22, 23 | "Not registered" and "New voter" are one thing, called "Eligible but Not Registered" | Replaces | Screen and menu names; one list | 7.5 |
| 24, 27 | Bulk message | Change request (small) | **No separate bulk screen and no bulk SMS.** The multi-send is WhatsApp to at most 5 voters at a time (one family is sent by picking its members). This is less than the PDF asks; the app flow shows it for the client to confirm | 7.12 |
| 25, 26 | Call, SMS or WhatsApp to one voter from the profile | Same | Built (5.9) | – |
| 7 (intro) | Every report at three levels: AC, Village Panchayat, Part / Booth | Change request | The guessed "ward" level becomes Village Panchayat or Municipal Council (see "Goa, not Maharashtra" below). The client sends which parts belong to which panchayat | 14.1 |
| 28 | Surname search | Change request | A Surname filter in search, on the phone and the server | 14.2 |
| 29, 30, Expected reports | Surname summary, surname list, AC / Village Panchayat / part summaries, male / female / third gender count, influencer list, Eligible but Not Registered list; filters AC, Village Panchayat, part, surname, gender, age range, influencer; download as Excel, PDF and CSV | Change request | Reports need internet. A surveyor gets them for the assigned parts, a supervisor for the assigned panchayats, an admin for the constituency | 14.3–14.5 |
| 31–35 | Matching Engine as its own menu item: compare old and new roll, new / deleted / changed voters, keep survey data, see the results, download a report | Replaces + change request | "Roll update" is renamed Matching Engine (the comparing itself was already in the SRS). The results screen and the report download are new | Step 10, 14.6 |
| 9 (Know My Constituency) | Geography by Village Panchayat and part, demographics, previous MP / AC / ZP election results; admin and core staff only | Change request | Geography and demographics are worked out from the data already in JANSETU. Previous election results are typed in from what the client gives. "Core staff" = super admin, so admin and super admin see it | 14.7, 14.8 |
| 36–38 | Put all of it in the app flow | – | `docs/app_flow_v2.pdf` | Flow |
| 39, 40 | Everything on the portal and the app, with sync and permissions | – | Each task names its portal part for the teammate | all |

### Goa, not Maharashtra

AC 2 (Pernem, SC) is in Goa (roll code S05). The client's list mixes the two states' systems; JANSETU follows Goa's.

| | Goa (used) | Maharashtra (not used here) |
|---|---|---|
| Local bodies | Two levels: Village Panchayat, then Zilla Panchayat (North Goa, South Goa). Towns have a Municipal Council | Three levels: Gram Panchayat, Panchayat Samiti, Zilla Parishad |
| Village heads | Sarpanch, Deputy Sarpanch, Panch | Sarpanch, Up-Sarpanch, Gram Panchayat member |
| Between AC and part | Village Panchayat or Municipal Council | Gat / Gan (Zilla Parishad and Panchayat Samiti divisions), ward |

- The middle level is "Village Panchayat / Municipal Council": Pernem town is a Municipal Council, so its parts are in no village panchayat.
- "ZP" is Zilla Panchayat. Pernem taluka has four ZP constituencies: Arambol, Morjim, Dhargal, Torxem.
- "Up Sarpanch" in the client's list is Goa's Deputy Sarpanch. The list is kept as the client wrote it and can be edited under Lists & labels; the app flow points this out.
- Which panchayats are in AC 2 is not settled from public sources (Pernem taluka's panchayats are split between AC 1 Mandrem and AC 2 Pernem). The client's part-to-panchayat list is the source.
- The schema's `taluka`, `gat` and `gan` levels stay unused for Goa.

Sources: Goa State Election Commission (sec.goa.gov.in), goa.gov.in (North Goa Zilla Panchayat), CAG reports on Goa's local bodies, CEO Goa roll pages for AC 2.

### Still open with the client (asked in the app flow)

1. Kutumb Connect made by the surveyor, not from house numbers (differs from PDF item 7).
2. WhatsApp to at most 5 voters as the bulk option; no bulk SMS (less than PDF items 24, 27).
3. The list of parts in each Village Panchayat / Municipal Council.
4. Previous election results: which elections and years, and whether the figures are per part, per panchayat or for the whole constituency.
5. "Up Sarpanch" or "Deputy Sarpanch" in the influencer list.
6. Time and cost of the change requests, and which of them must be in the 15 Dec delivery.

## 12 Nov 2026 (morning): first list, in SRS 1.1

Approved by the client on 12 Nov as SRS version 1.1 (`docs/01_srs.md`, "Changes in 1.1"). Replaced by the evening list where the two differ:

| Morning note | Evening |
|---|---|
| Important voter with a position list | Removed |
| Influencer with a type list (types not named) | The 11 entries above |
| Important voters filter | Influencer filter |
| WhatsApp to at most 5 families, every voter in them | At most 5 voters |
| Families made by hand, free-text name | Same, now called Kutumb Connect, no head |
