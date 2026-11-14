"""Possible duplicates and repeated voters (plan 10.5): find the pairs a person should check.

A pair = two live voters of one constituency with the same name, the same relative's name and the
same gender, whose ages differ by at most MAX_AGE_GAP (or one has no age). English names, or the
Marathi ones where the English are empty. Source "roll_flag" when either is marked repeated in the
roll, else "fuzzy_match". Pairs are stored once (voter_a_id < voter_b_id) and never removed here:
a decision (same person / different people) stays even if a voter later changes.

Run after a roll apply (that constituency), after a hand add or correction (that voter), and once
for data already on record: scripts/find_duplicates.py. Real roll (13 Nov): 24 pairs, ~0.3 s.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Connection, text

MAX_AGE_GAP = 2

_KEY = """lower(coalesce(nullif({a}.full_name_en, ''), {a}.full_name_mr)),
          lower(coalesce({a}.relative_name_en, {a}.relative_name_mr, '')), {a}.gender"""


def find_pairs(conn: Connection, local_body_id: uuid.UUID, voter_id: uuid.UUID | None = None) -> int:
    """Store the constituency's new pairs (only those with `voter_id`, when given). Returns how many."""
    return conn.execute(text(f"""
        INSERT INTO app.voter_duplicate_pairs (tenant_id, voter_a_id, voter_b_id, source, similarity)
        SELECT app.current_tenant_id(), a.id, b.id,
               CASE WHEN a.is_repeated_in_roll OR b.is_repeated_in_roll THEN 'roll_flag' ELSE 'fuzzy_match' END, 1
          FROM app.voters a
          JOIN app.voters b ON b.tenant_id = a.tenant_id AND b.local_body_id = a.local_body_id AND a.id < b.id
                           AND ({_KEY.format(a='a')}) = ({_KEY.format(a='b')})
                           AND (a.age IS NULL OR b.age IS NULL OR abs(a.age - b.age) <= :gap)
         WHERE a.local_body_id = :lb AND a.deleted_at IS NULL AND b.deleted_at IS NULL
           AND coalesce(nullif(a.full_name_en, ''), a.full_name_mr, '') <> ''
           AND (CAST(:vid AS uuid) IS NULL OR :vid IN (a.id, b.id))
        ON CONFLICT (tenant_id, voter_a_id, voter_b_id) DO NOTHING
    """), {"lb": local_body_id, "vid": voter_id, "gap": MAX_AGE_GAP}).rowcount
