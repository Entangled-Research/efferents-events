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


def test_default_tokens_last_48_hours(tmp_path):
    from datetime import datetime, timedelta, timezone
    from efferents.cluster.config import SessionPolicy
    assert SessionPolicy().max_age_hours == 48
    store = ow.OwnerStore(tmp_path / "owners.json")
    owner = store.join("Ada")
    owner.joined_at = (datetime.now(timezone.utc) - timedelta(hours=47)).isoformat()
    assert store.by_token(owner.token) is owner
    owner.joined_at = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
    assert store.by_token(owner.token) is None


def test_recovery_preserves_identity_and_renews_without_resetting_join_date(tmp_path):
    store = ow.OwnerStore(tmp_path / 'owners.json')
    owner = store.join('Ada')
    store.add_lab(owner.owner_id, 'ada-lab')
    key = store.create_recovery_key(owner.owner_id)
    original_token = owner.token
    owner.joined_at = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    joined = owner.joined_at
    store._save()
    assert key not in store.path.read_text()
    with pytest.raises(ControlError):
        store.recover(original_token)
    store = ow.OwnerStore(store.path)
    recovered = store.recover(key)
    assert recovered.owner_id == owner.owner_id
    assert recovered.joined_at == joined
    assert recovered.token == original_token
    assert recovered.labs == ['ada-lab']
    assert store.by_token(original_token) is recovered
    replacement = store.create_recovery_key(recovered.owner_id)
    with pytest.raises(ControlError):
        store.recover(key)
    assert store.recover(replacement).owner_id == owner.owner_id


def test_merged_recovery_and_session_renewal_survive_restart(tmp_path):
    store = ow.OwnerStore(tmp_path / "owners.json", max_age_hours=1)
    target, source = store.join("Masha"), store.join("Test")
    old_key = store.create_recovery_key(source.owner_id)
    old_token = source.token
    joined = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    source.joined_at = target.joined_at = joined
    store._save()
    assert store.by_token(old_token) is None
    store.merge(target.owner_id, [source.owner_id])
    reloaded = ow.OwnerStore(store.path, max_age_hours=1)
    renewed = reloaded.by_token(old_token)
    assert renewed.owner_id == target.owner_id
    assert renewed.joined_at == joined and renewed.renewed_at
    assert reloaded.recover(old_key).owner_id == target.owner_id
    replacement = reloaded.create_recovery_key(source.owner_id)
    reloaded = ow.OwnerStore(store.path, max_age_hours=1)
    with pytest.raises(ControlError):
        reloaded.recover(old_key)
    assert reloaded.recover(replacement).owner_id == target.owner_id
    assert reloaded.by_token(old_token).owner_id == target.owner_id


def test_invalid_or_unicode_tokens_fail_closed_and_legacy_dates_do_not_crash(tmp_path):
    store = ow.OwnerStore(tmp_path / "owners.json")
    owner = store.join("Ada")
    assert store.by_token("not-a-token-é") is None
    owner.joined_at = "not-a-date"
    assert store.by_token(owner.token) is None
    owner.joined_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    assert store.by_token(owner.token).owner_id == owner.owner_id
