"""Unit tests for role hierarchy + RFC7807 rendering — no DB."""

from __future__ import annotations

from apps.tooling.api.deps import ROLE_ORDER, CurrentUser
from apps.tooling.api.errors import Conflict, NotFound, Unprocessable


def test_role_order_monotonic():
    assert ROLE_ORDER["viewer"] < ROLE_ORDER["operator"] < ROLE_ORDER["setter"] < ROLE_ORDER["admin"]


def test_current_user_rank_unknown_role():
    import uuid
    u = CurrentUser(id=uuid.uuid4(), username="x", role="bogus")
    assert u.rank() == -1


def test_problem_document_shape():
    resp = NotFound("tool 123 missing").to_response()
    assert resp.status_code == 404
    assert resp.media_type == "application/problem+json"


def test_conflict_extra_fields():
    err = Conflict("busy", active_assignments=3)
    body = err.extra
    assert body["active_assignments"] == 3
    assert err.status == 409


def test_unprocessable_field():
    err = Unprocessable("bad", field="t_number")
    assert err.status == 422
    assert err.extra["field"] == "t_number"
