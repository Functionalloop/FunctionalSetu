"""Lists and labels (9.4): castes, professions, influencer types, colour tags, custom survey fields, message
texts. Admin and super admin; one set per workspace (RLS).

Entries are never deleted, only switched off (old surveys keep pointing at them; the survey save refuses an
inactive one). Every change stamps sync_xid, so phones get it on their next pull (`lists`).
`/masters/{list}` in the API document is one explicit route per list (each list has its own shape and key).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from ..deps import Db
from ..errors import ApiError
from ..schemas import ColorTag, CustomFieldLabel, NamedListEntry
from ..schemas_admin import (ColorTagIn, CustomFieldKey, CustomFieldLabelIn, MessageTemplate, MessageTemplateIn,
                             NamedEntryIn, TemplateKind)
from ..stubs import Admin

router = APIRouter(tags=["admin"])

_NAMED = "id, name_mr, name_en, name_hi, sort_order, is_active"
_COLOR = ", ".join(ColorTag.model_fields)


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def _unique_error(exc: DBAPIError, code: str, message: str) -> ApiError:
    if getattr(exc.orig, "sqlstate", None) == "23505":
        return ApiError(409, code, message)
    raise exc


# --- castes, professions, influencer types: same shape ----------------------------------------
def _named_list(conn: Connection, table: str) -> list[NamedListEntry]:
    rows = conn.execute(text(f"SELECT {_NAMED} FROM app.{table} ORDER BY sort_order, name_mr")).mappings().all()
    return [NamedListEntry(**r) for r in rows]


def _named_params(body: NamedEntryIn) -> dict:
    name_mr = body.name_mr.strip()
    if not name_mr:
        raise ApiError(422, "validation_error", "name_mr cannot be empty.")
    return {"name_mr": name_mr, "name_en": _clean(body.name_en), "name_hi": _clean(body.name_hi),
            "sort_order": body.sort_order, "is_active": body.is_active}


def _named_add(conn: Connection, table: str, tenant: uuid.UUID, body: NamedEntryIn) -> NamedListEntry:
    try:
        row = conn.execute(text(f"""
            INSERT INTO app.{table} (tenant_id, name_mr, name_en, name_hi, sort_order, is_active)
            VALUES (:tenant, :name_mr, :name_en, :name_hi, :sort_order, :is_active)
            RETURNING {_NAMED}
        """), {"tenant": tenant, **_named_params(body)}).mappings().one()
    except DBAPIError as exc:
        raise _unique_error(exc, "name_taken", "The list already has an entry with this Marathi name.") from None
    return NamedListEntry(**row)


def _named_update(conn: Connection, table: str, entry_id: uuid.UUID, body: NamedEntryIn) -> NamedListEntry:
    try:
        row = conn.execute(text(f"""
            UPDATE app.{table} SET name_mr = :name_mr, name_en = :name_en, name_hi = :name_hi,
                                   sort_order = :sort_order, is_active = :is_active
             WHERE id = :id RETURNING {_NAMED}
        """), {"id": entry_id, **_named_params(body)}).mappings().first()
    except DBAPIError as exc:
        raise _unique_error(exc, "name_taken", "The list already has an entry with this Marathi name.") from None
    if row is None:
        raise ApiError(404, "not_found", "Entry not found.")
    return NamedListEntry(**row)


@router.get("/masters/castes", response_model=list[NamedListEntry], summary="Castes, inactive included. Admin.")
def list_castes(conn: Db, user: Admin) -> list[NamedListEntry]:
    return _named_list(conn, "castes")


@router.post("/masters/castes", response_model=NamedListEntry, status_code=status.HTTP_201_CREATED,
             summary="Add a caste. Admin.")
def add_caste(body: NamedEntryIn, conn: Db, user: Admin) -> NamedListEntry:
    return _named_add(conn, "castes", user.tenant_id, body)


@router.patch("/masters/castes/{entry_id}", response_model=NamedListEntry,
              summary="Rename, reorder or switch off a caste (never deleted: old surveys keep it). Admin.")
def update_caste(entry_id: uuid.UUID, body: NamedEntryIn, conn: Db, user: Admin) -> NamedListEntry:
    return _named_update(conn, "castes", entry_id, body)


@router.get("/masters/professions", response_model=list[NamedListEntry], summary="Professions. Admin.")
def list_professions(conn: Db, user: Admin) -> list[NamedListEntry]:
    return _named_list(conn, "professions")


@router.post("/masters/professions", response_model=NamedListEntry, status_code=status.HTTP_201_CREATED,
             summary="Add a profession. Admin.")
def add_profession(body: NamedEntryIn, conn: Db, user: Admin) -> NamedListEntry:
    return _named_add(conn, "professions", user.tenant_id, body)


@router.patch("/masters/professions/{entry_id}", response_model=NamedListEntry,
              summary="Rename, reorder or switch off a profession. Admin.")
def update_profession(entry_id: uuid.UUID, body: NamedEntryIn, conn: Db, user: Admin) -> NamedListEntry:
    return _named_update(conn, "professions", entry_id, body)


@router.get("/masters/influencer-types", response_model=list[NamedListEntry],
            summary="Influencer types (Sarpanch, MLA, ...), inactive included. Admin.")
def list_influencer_types(conn: Db, user: Admin) -> list[NamedListEntry]:
    return _named_list(conn, "influencer_types")


@router.post("/masters/influencer-types", response_model=NamedListEntry, status_code=status.HTTP_201_CREATED,
             summary="Add an influencer type. Admin.")
def add_influencer_type(body: NamedEntryIn, conn: Db, user: Admin) -> NamedListEntry:
    return _named_add(conn, "influencer_types", user.tenant_id, body)


@router.patch("/masters/influencer-types/{entry_id}", response_model=NamedListEntry,
              summary="Rename, reorder or switch off an influencer type (never deleted). Admin.")
def update_influencer_type(entry_id: uuid.UUID, body: NamedEntryIn, conn: Db, user: Admin) -> NamedListEntry:
    return _named_update(conn, "influencer_types", entry_id, body)


# --- colour tags ----------------------------------------------------------------------------------
def _color_params(body: ColorTagIn) -> dict:
    label_mr, label_en = body.label_mr.strip(), body.label_en.strip()
    if not label_mr or not label_en:
        raise ApiError(422, "validation_error", "label_mr and label_en cannot be empty.")
    if body.is_default and not body.is_active:
        raise ApiError(422, "validation_error", "A switched-off tag cannot be the default.")
    return {"code": body.code, "hex": body.hex.upper(), "label_mr": label_mr, "label_en": label_en,
            "label_hi": _clean(body.label_hi), "is_default": body.is_default, "sort_order": body.sort_order,
            "is_active": body.is_active}


def _clear_default(conn: Connection, body: ColorTagIn, keep: uuid.UUID | None = None) -> None:
    """One default per workspace (unique index): a new default takes the place of the old one."""
    if body.is_default:
        conn.execute(text("UPDATE app.color_tags SET is_default = false WHERE is_default AND id IS DISTINCT FROM :k"),
                     {"k": keep})


_CODE_TAKEN = "Another colour tag already has this code."


@router.get("/masters/color-tags", response_model=list[ColorTag], summary="Colour tags. Admin.")
def list_color_tags(conn: Db, user: Admin) -> list[ColorTag]:
    rows = conn.execute(text(f"SELECT {_COLOR} FROM app.color_tags ORDER BY sort_order, code")).mappings().all()
    return [ColorTag(**r) for r in rows]


@router.post("/masters/color-tags", response_model=ColorTag, status_code=status.HTTP_201_CREATED,
             summary="Add a colour tag. Admin.")
def add_color_tag(body: ColorTagIn, conn: Db, user: Admin) -> ColorTag:
    params = _color_params(body)
    _clear_default(conn, body)
    try:
        row = conn.execute(text(f"""
            INSERT INTO app.color_tags (tenant_id, code, hex, label_mr, label_en, label_hi, is_default, sort_order,
                                        is_active)
            VALUES (:tenant, :code, :hex, :label_mr, :label_en, :label_hi, :is_default, :sort_order, :is_active)
            RETURNING {_COLOR}
        """), {"tenant": user.tenant_id, **params}).mappings().one()
    except DBAPIError as exc:
        raise _unique_error(exc, "code_taken", _CODE_TAKEN) from None
    return ColorTag(**row)


@router.patch("/masters/color-tags/{entry_id}", response_model=ColorTag,
              summary="Change a colour tag's label, colour, order or switch it off. Admin.")
def update_color_tag(entry_id: uuid.UUID, body: ColorTagIn, conn: Db, user: Admin) -> ColorTag:
    params = _color_params(body)
    if conn.execute(text("SELECT 1 FROM app.color_tags WHERE id = :id"), {"id": entry_id}).first() is None:
        raise ApiError(404, "not_found", "Colour tag not found.")
    _clear_default(conn, body, keep=entry_id)
    try:
        row = conn.execute(text(f"""
            UPDATE app.color_tags SET code = :code, hex = :hex, label_mr = :label_mr, label_en = :label_en,
                                      label_hi = :label_hi, is_default = :is_default, sort_order = :sort_order,
                                      is_active = :is_active
             WHERE id = :id RETURNING {_COLOR}
        """), {"id": entry_id, **params}).mappings().one()
    except DBAPIError as exc:
        raise _unique_error(exc, "code_taken", _CODE_TAKEN) from None
    return ColorTag(**row)


# --- custom survey fields (Extra Check 1-2, Extra Info 1-5) ---------------------------------------
_CUSTOM = "field_key::text AS field_key, label_mr, label_en, label_hi, is_enabled"


@router.get("/masters/custom-fields", response_model=list[CustomFieldLabel],
            summary="Labels of the survey's custom fields (Extra Check 1-2, Extra Info 1-5). Admin.")
def list_custom_fields(conn: Db, user: Admin) -> list[CustomFieldLabel]:
    rows = {r["field_key"]: r for r in conn.execute(
        text(f"SELECT {_CUSTOM} FROM app.custom_field_labels")).mappings().all()}
    # every key, also one without a row yet (disabled, no label)
    return [CustomFieldLabel(**rows[k.value]) if k.value in rows else
            CustomFieldLabel(field_key=k.value, label_mr=None, label_en=None, label_hi=None, is_enabled=False)
            for k in CustomFieldKey]


@router.patch("/masters/custom-fields/{field_key}", response_model=CustomFieldLabel,
              summary="Name, enable or disable one custom field. Admin.")
def update_custom_field(field_key: CustomFieldKey, body: CustomFieldLabelIn, conn: Db,
                        user: Admin) -> CustomFieldLabel:
    label_mr, label_en = _clean(body.label_mr), _clean(body.label_en)
    if body.is_enabled and not (label_mr or label_en):
        raise ApiError(422, "validation_error", "An enabled field needs a Marathi or English label.")
    row = conn.execute(text(f"""
        INSERT INTO app.custom_field_labels (tenant_id, field_key, label_mr, label_en, label_hi, is_enabled)
        VALUES (:tenant, CAST(:key AS app.custom_field_key), :mr, :en, :hi, :on)
        ON CONFLICT (tenant_id, field_key) DO UPDATE
           SET label_mr = EXCLUDED.label_mr, label_en = EXCLUDED.label_en, label_hi = EXCLUDED.label_hi,
               is_enabled = EXCLUDED.is_enabled
        RETURNING {_CUSTOM}
    """), {"tenant": user.tenant_id, "key": field_key.value, "mr": label_mr, "en": label_en,
           "hi": _clean(body.label_hi), "on": body.is_enabled}).mappings().one()
    return CustomFieldLabel(**row)


# --- message texts ----------------------------------------------------------------------------------
_TEMPLATE = "kind, body_mr, body_en, body_hi, updated_at"


@router.get("/masters/message-templates", response_model=list[MessageTemplate],
            summary="Message texts: birthday, slip by WhatsApp / SMS, general. Admin.")
def list_message_templates(conn: Db, user: Admin) -> list[MessageTemplate]:
    # Every kind, also one never saved (the seed makes only the birthday text): empty, dated when the
    # workspace was made.
    rows = conn.execute(text(f"""
        SELECT k.kind, m.body_mr, m.body_en, m.body_hi, coalesce(m.updated_at, t.created_at) AS updated_at
          FROM unnest(CAST(:kinds AS text[])) AS k(kind)
          CROSS JOIN app.tenants t
          LEFT JOIN app.message_templates m ON m.kind = k.kind
         ORDER BY k.kind
    """), {"kinds": [k.value for k in TemplateKind]}).mappings().all()
    return [MessageTemplate(**r) for r in rows]


@router.patch("/masters/message-templates/{kind}", response_model=MessageTemplate,
              summary="Change one message text. Admin.")
def update_message_template(kind: TemplateKind, body: MessageTemplateIn, conn: Db, user: Admin) -> MessageTemplate:
    row = conn.execute(text(f"""
        INSERT INTO app.message_templates (tenant_id, kind, body_mr, body_en, body_hi, updated_by)
        VALUES (:tenant, :kind, :mr, :en, :hi, :by)
        ON CONFLICT (tenant_id, kind) DO UPDATE
           SET body_mr = EXCLUDED.body_mr, body_en = EXCLUDED.body_en, body_hi = EXCLUDED.body_hi,
               updated_by = EXCLUDED.updated_by
        RETURNING {_TEMPLATE}
    """), {"tenant": user.tenant_id, "kind": kind.value, "mr": _clean(body.body_mr), "en": _clean(body.body_en),
           "hi": _clean(body.body_hi), "by": user.user_id}).mappings().one()
    return MessageTemplate(**row)
