from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from efferents.cluster import owners as ow
from efferents.dashboard.control import ControlError


def test_join_assigns_token_and_persists_0600(tmp_path):
    store = ow.OwnerStore(tmp_path / "owners.json")
    ada = store.join("Ada", ip="1.2.3.4")
    assert len(ada.token) > 30 and ada.owner_id
    assert (tmp_path / "owners.json").stat().st_mode & 0o777 == 0o600
    reloaded = ow.OwnerStore(tmp_path / "owners.json")
    assert reloaded.by_token(ada.token).name == "Ada"
    assert reloaded.by_token("nope") is None and reloaded.by_token(None) is None


def test_names_unique_case_insensitive_and_validated(tmp_path):
    store = ow.OwnerStore(tmp_path / "owners.json")
    store.join("Ada Lovelace")
    with pytest.raises(ControlError) as exc:
        store.join("ada   lovelace")
    assert exc.value.status == 409
    for bad in ("", "x" * 41, "<script>", "a\x00b"):
        with pytest.raises(ControlError):
            store.join(bad)


def test_expiry(tmp_path):
    store = ow.OwnerStore(tmp_path / "owners.json", max_age_hours=1)
    ada = store.join("Ada")
    ada.joined_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    assert store.by_token(ada.token) is None
    forever = ow.OwnerStore(tmp_path / "o2.json", max_age_hours=0)
    bob = forever.join("Bob")
    bob.joined_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    assert forever.by_token(bob.token) is bob


def test_add_lab_and_owner_of(tmp_path):
    store = ow.OwnerStore(tmp_path / "owners.json")
    ada = store.join("Ada")
    store.add_lab(ada.owner_id, "ada-lab")
    store.add_lab(ada.owner_id, "ada-lab")
    assert ada.labs == ["ada-lab"]
    assert store.owner_of("ada-lab") is ada and store.owner_of("x") is None
    data = json.loads((tmp_path / "owners.json").read_text())
    assert data["owners"][ada.owner_id]["labs"] == ["ada-lab"]


def test_cookie_roundtrip():
    header = ow.build_cookie("tok", max_age_s=3600, secure=True)
    assert "HttpOnly" in header and "SameSite=Lax" in header and "Secure" in header
    assert ow.token_from_cookie_header(f"other=1; {ow.COOKIE_NAME}=tok") == "tok"
    assert ow.token_from_cookie_header(None) is None
    assert "Secure" not in ow.build_cookie("t", max_age_s=1, secure=False)
