"""get_or_provision_tenant_user: membership-gated local-user provisioning (Phase 6A)."""

from __future__ import annotations

from dataclasses import dataclass

from open_webui.test.conftest import run
from open_webui.utils import auth as A


@dataclass
class _User:
    id: str
    role: str


class _Users:
    """Stand-in for the Users model singleton."""

    def __init__(self, get_returns, insert_result=None, insert_exc=None):
        self._get_returns = list(get_returns)
        self.insert_result = insert_result
        self.insert_exc = insert_exc
        self.inserted = None
        self.updated = None

    async def get_user_by_email(self, email, db=None):
        return self._get_returns.pop(0)

    async def insert_new_user(self, *, id, name, email, role, oauth=None, db=None):
        self.inserted = {'id': id, 'name': name, 'email': email, 'role': role, 'oauth': oauth}
        if self.insert_exc:
            raise self.insert_exc
        return self.insert_result

    async def update_user_role_by_id(self, uid, role, db=None):
        self.updated = {'id': uid, 'role': role}
        return _User(uid, role)


def test_provisions_when_absent(monkeypatch, make_context):
    ctx = make_context(role='user')  # identity email == 'a@acme.com'
    fake = _Users(get_returns=[None], insert_result=_User('user_01H', 'user'))
    monkeypatch.setattr(A, 'Users', fake)

    user = run(A.get_or_provision_tenant_user(ctx))

    assert user.id == 'user_01H'
    assert fake.inserted['email'] == 'a@acme.com'  # keyed on email
    assert fake.inserted['role'] == 'user'  # role from IAM membership
    assert fake.inserted['oauth'] == {'workos': {'email': 'a@acme.com'}}


def test_returns_existing_same_role(monkeypatch, make_context):
    ctx = make_context(role='admin')
    fake = _Users(get_returns=[_User('user_01H', 'admin')])
    monkeypatch.setattr(A, 'Users', fake)

    user = run(A.get_or_provision_tenant_user(ctx))

    assert user.role == 'admin'
    assert fake.inserted is None  # not re-provisioned
    assert fake.updated is None  # role already matches


def test_syncs_role_when_membership_changed(monkeypatch, make_context):
    ctx = make_context(role='admin')  # IAM now says admin
    fake = _Users(get_returns=[_User('user_01H', 'user')])  # local row is stale
    monkeypatch.setattr(A, 'Users', fake)

    user = run(A.get_or_provision_tenant_user(ctx))

    assert fake.updated == {'id': 'user_01H', 'role': 'admin'}
    assert user.role == 'admin'


def test_provision_race_refetches(monkeypatch, make_context):
    # Two concurrent first requests: insert loses the PK race, so we re-fetch.
    ctx = make_context(role='user')
    fake = _Users(get_returns=[None, _User('user_01H', 'user')], insert_exc=Exception('duplicate key'))
    monkeypatch.setattr(A, 'Users', fake)

    user = run(A.get_or_provision_tenant_user(ctx))

    assert user.id == 'user_01H'  # recovered, no raise
