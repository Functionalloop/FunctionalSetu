"""Election settings (9.4): GET/PUT /settings/election. Admin and super admin (both may save the election and
the candidate, decided in the plan).

One row per workspace (app.tenant_settings, made by seed_tenant_defaults). PUT replaces every editable field,
like the survey: a field left out is cleared (or gets its default). `feature_bluetooth_printer` (phase 2) is
not in the body and is kept. Phones get the change on their next pull (`settings`, by sync_xid) and from /me;
there the candidate fields are blanked while code_of_conduct_mode is on, here they never are.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import Connection, text

from ..deps import Db
from ..errors import ApiError
from ..schemas_admin import ElectionSettings, ElectionSettingsIn
from ..stubs import Admin

router = APIRouter(tags=["admin"])

# The CHECK constraints of tenant_settings, so a wrong value is a 422 and not a database error.
ELECTION_TYPES = frozenset({"nagarpalika", "nagar_panchayat", "municipal_corporation", "zilla_parishad",
                            "panchayat_samiti", "gram_panchayat", "vidhan_sabha", "lok_sabha", "other"})
SMS_FIELDS = frozenset({"election_name", "middle_name", "booth_address", "candidate_info", "party_name", "symbol"})
# Settings that point at an uploaded image, and the kind of file each must be.
FILE_FIELDS = {"candidate_photo_file_id": "candidate_photo", "symbol_file_id": "symbol",
               "slip_header_file_id": "slip_header", "whatsapp_slip_file_id": "whatsapp_slip"}
TEXT_FIELDS = ("election_code", "election_name_mr", "election_name_en", "candidate_name_mr", "candidate_name_en",
               "party_name_mr", "party_name_en", "candidate_message_mr", "candidate_message_en", "message_start_mr",
               "message_start_en", "message_end_mr", "message_end_en", "middle_name_separator")


def load_election_settings(conn: Connection) -> ElectionSettings:
    row = conn.execute(text("SELECT * FROM app.tenant_settings")).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "This workspace has no settings yet.")
    return ElectionSettings(**{k: row[k] for k in ElectionSettings.model_fields})


def _check_files(conn: Connection, values: dict) -> None:
    for field, kind in FILE_FIELDS.items():
        file_id = values[field]
        if file_id is None:
            continue
        found = conn.execute(text("SELECT kind::text FROM app.files WHERE id = :id AND deleted_at IS NULL"),
                             {"id": file_id}).scalar()
        if found is None:
            raise ApiError(422, "validation_error", f"{field}: no such file (upload it with POST /files first).")
        if found != kind:
            raise ApiError(422, "validation_error", f"{field}: the file is a {found}, not a {kind}.")


@router.get("/settings/election", response_model=ElectionSettings,
            summary="Election, candidate, slip text and feature switches (candidate shown even in code of conduct). Admin.")
def get_election_settings(conn: Db, user: Admin) -> ElectionSettings:
    return load_election_settings(conn)


@router.put("/settings/election", response_model=ElectionSettings, summary="Save the election settings. Admin.")
def set_election_settings(body: ElectionSettingsIn, conn: Db, user: Admin) -> ElectionSettings:
    values = body.model_dump()
    for f in TEXT_FIELDS:
        values[f] = (values[f] or "").strip() or None
    if values["election_type"] is not None:
        values["election_type"] = values["election_type"].strip().lower()
        if values["election_type"] not in ELECTION_TYPES:
            raise ApiError(422, "validation_error",
                           f"election_type must be one of: {', '.join(sorted(ELECTION_TYPES))}.")
    values["sms_fields"] = list(dict.fromkeys(values["sms_fields"]))
    if bad := [f for f in values["sms_fields"] if f not in SMS_FIELDS]:
        raise ApiError(422, "validation_error", f"sms_fields: unknown field {bad[0]}.")
    values["default_language"] = body.default_language.value
    _check_files(conn, values)

    conn.execute(text("INSERT INTO app.tenant_settings (tenant_id) VALUES (:t) ON CONFLICT DO NOTHING"),
                 {"t": user.tenant_id})
    sets = ", ".join(f"{k} = :{k}" for k in values if k != "default_language")
    conn.execute(text(f"""UPDATE app.tenant_settings
                             SET {sets}, default_language = CAST(:default_language AS app.lang), updated_by = :by"""),
                 {**values, "by": user.user_id})
    return load_election_settings(conn)
