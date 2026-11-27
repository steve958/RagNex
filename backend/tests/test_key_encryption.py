"""Workspace model API keys are encrypted at rest (core/encryption.py)."""

from __future__ import annotations

import base64
import datetime as dt
import secrets
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core import encryption
from backend.app.core.config import Settings, settings
from backend.app.core.db import get_engine
from backend.app.models.tenant import Tenant
from backend.app.services import model_settings, stored_secrets

from test_model_settings import SECRET, Client, api  # noqa: F401 (api is a fixture)


def _new_key() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


@pytest_asyncio.fixture
async def keys(monkeypatch):
    """Switch the server's encryption keys: keys(current, previous=[...]).

    Keys saved meanwhile are encrypted under throwaway keys, so afterwards they're removed:
    left in the shared dev database they'd stay unreadable for good."""
    started = dt.datetime.now(dt.timezone.utc)

    def use(current: str, previous: list[str] | None = None) -> None:
        monkeypatch.setattr(settings, "ragnex_encryption_key", current)
        monkeypatch.setattr(settings, "ragnex_encryption_previous_keys", previous or [])

    yield use

    async with async_sessionmaker(get_engine(), expire_on_commit=False)() as db:
        await db.execute(
            sa.update(Tenant)
            .where(Tenant.created_at >= started)
            .values(
                llm_config=Tenant.llm_config.op("-")("api_key"),
                embedding_config=Tenant.embedding_config.op("-")("api_key"),
            )
        )
        await db.commit()


async def _stored(tenant_id: str) -> tuple[dict, dict]:
    async with async_sessionmaker(get_engine(), expire_on_commit=False)() as db:
        row = (await db.execute(sa.select(Tenant.llm_config, Tenant.embedding_config).where(
            Tenant.id == uuid.UUID(tenant_id)
        ))).one()
        return dict(row.llm_config or {}), dict(row.embedding_config or {})


# --- The encryption itself -----------------------------------------------------------------


def test_round_trip_and_format():
    token = encryption.encrypt(SECRET)
    assert token.startswith("enc:v1:") and SECRET not in token
    assert encryption.decrypt(token) == SECRET
    assert encryption.encrypt(SECRET) != token  # random IV: equal keys don't look equal


def test_wrong_key_and_tampering_are_detected(keys):
    token = encryption.encrypt(SECRET)

    tampered = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]
    with pytest.raises(encryption.SecretUnavailable):
        encryption.decrypt(tampered)

    keys(_new_key())
    with pytest.raises(encryption.SecretUnavailable, match="RAGNEX_ENCRYPTION_KEY has changed"):
        encryption.decrypt(token)


def test_rotation_with_previous_keys(keys):
    old, new = _new_key(), _new_key()
    keys(old)
    token = encryption.encrypt(SECRET)

    keys(new, previous=[old])
    assert encryption.decrypt(token) == SECRET  # old values still readable during rotation
    rotated = encryption.reencrypt(token)

    keys(new)  # old key dropped
    assert encryption.decrypt(rotated) == SECRET
    with pytest.raises(encryption.SecretUnavailable):
        encryption.decrypt(token)


def test_values_stored_before_encryption_still_read():
    assert encryption.decrypt("sk-plain-old") == "sk-plain-old"
    assert encryption.decrypt(encryption.reencrypt("sk-plain-old")) == "sk-plain-old"


@pytest.mark.parametrize(
    "key",
    [
        base64.b64encode(b"k" * 32).decode(),  # openssl rand -base64 32
        Fernet.generate_key().decode(),  # URL-safe alphabet
    ],
)
def test_accepted_key_formats(key):
    assert len(base64.urlsafe_b64decode(encryption.normalize_key(key))) == 32


@pytest.mark.parametrize("bad", ["", "change-me", base64.b64encode(b"short").decode(), "!" * 44])
def test_server_refuses_to_start_without_a_valid_key(bad):
    with pytest.raises(ValidationError, match="RAGNEX_ENCRYPTION_KEY"):
        Settings(ragnex_encryption_key=bad, jwt_secret=secrets.token_hex(32))


def test_bad_previous_key_is_reported():
    with pytest.raises(ValidationError, match="RAGNEX_ENCRYPTION_PREVIOUS_KEYS entry 1"):
        Settings(
            ragnex_encryption_key=_new_key(),
            ragnex_encryption_previous_keys=["nope"],
            jwt_secret=secrets.token_hex(32),
        )


# --- Through the API -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keys_are_stored_encrypted_and_used_decrypted(api):
    owner = await Client(api).register()
    r = await owner.put({"llm": {"model": "m", "api_key": SECRET}, "embedding": {"api_key": SECRET + "-emb"}})
    assert r.status_code == 200, r.text

    llm, emb = await _stored(owner.tenant_id)
    for section, plain in ((llm, SECRET), (emb, SECRET + "-emb")):
        assert section["api_key"].startswith("enc:v1:")
        assert plain not in str(section)

    # What chat, search and indexing get is the real key.
    async with async_sessionmaker(get_engine(), expire_on_commit=False)() as db:
        assert (await model_settings.load_tenant_llm_config(db, uuid.UUID(owner.tenant_id))).api_key == SECRET
    from backend.app.services.search import SearchService
    from backend.app.tasks.indexing import _load_embedding_config

    tid = uuid.UUID(owner.tenant_id)
    assert (await SearchService()._load_embedding_config(tid)).api_key == SECRET + "-emb"
    assert (await _load_embedding_config(tid)).api_key == SECRET + "-emb"

    # Changing other settings keeps the key (still encrypted, not double-encrypted).
    r = await owner.put({"llm": {"model": "other"}})
    assert r.status_code == 200
    async with async_sessionmaker(get_engine(), expire_on_commit=False)() as db:
        assert (await model_settings.load_tenant_llm_config(db, tid)).api_key == SECRET


@pytest.mark.asyncio
async def test_unreadable_key_is_explained_and_can_be_replaced(api, keys, monkeypatch):
    from backend.app.api.v1 import chat as chat_module

    owner = await Client(api).register()
    assert (await owner.put({"llm": {"model": "m", "api_key": SECRET}})).status_code == 200

    keys(_new_key())  # the server's key changed and the old one wasn't kept

    # Settings still open, and say the key needs entering again.
    r = await owner.get()
    assert r.status_code == 200, r.text
    assert r.json()["llm"]["has_api_key"] is True and r.json()["llm"]["api_key_readable"] is False

    # Chat explains instead of failing with a bare 500 (or calling the model without a key).
    from backend.app.services.search import SearchHit

    async def fake_search(self, *, tenant_id, kb_ids, query, top_k=10, **_):
        return [SearchHit("c1", "d1", str(kb_ids[0]), str(tenant_id), "ctx", 1.0, "hybrid")]

    monkeypatch.setattr(chat_module.SearchService, "search", fake_search)
    monkeypatch.setattr(chat_module, "_make_llm_service", lambda cfg: pytest.fail("model called"))
    headers = {**owner.auth, "X-Tenant-ID": owner.tenant_id}
    kb = (await api.post("/api/v1/knowledgebases", json={"name": "kb"}, headers=headers)).json()["id"]
    session = (await api.post("/api/v1/chat/sessions", json={"kb_ids": [kb]}, headers=headers)).json()["id"]
    r = await api.post(f"/api/v1/chat/sessions/{session}/messages", json={"content": "hi"}, headers=headers)
    assert r.status_code == 503
    assert "enter the key again" in r.json()["detail"]

    # The owner can change other settings and enter the key again.
    assert (await owner.put({"llm": {"model": "m2"}})).status_code == 200
    r = await owner.put({"llm": {"model": "m2", "api_key": "sk-new"}})
    assert r.status_code == 200 and r.json()["llm"]["api_key_readable"] is True


@pytest.mark.asyncio
async def test_reencrypt_command_moves_keys_to_the_new_key(api, keys):
    old, new = _new_key(), _new_key()
    keys(old)
    owner = await Client(api).register()
    assert (await owner.put({"llm": {"model": "m", "api_key": SECRET}})).status_code == 200
    before, _ = await _stored(owner.tenant_id)

    keys(new, previous=[old])
    report = await stored_secrets.run(rewrite=True)
    assert report.rewritten >= 1

    keys(new)  # old key retired
    after, _ = await _stored(owner.tenant_id)
    assert after["api_key"] != before["api_key"]
    assert encryption.decrypt(after["api_key"]) == SECRET
    assert (uuid.UUID(owner.tenant_id), "llm") not in (await stored_secrets.run(rewrite=False)).unreadable


@pytest.mark.asyncio
async def test_check_command_lists_unreadable_keys(api, keys):
    owner = await Client(api).register()
    assert (await owner.put({"llm": {"model": "m", "api_key": SECRET}})).status_code == 200
    keys(_new_key())
    report = await stored_secrets.run(rewrite=False)
    assert (uuid.UUID(owner.tenant_id), "llm") in report.unreadable
    assert f"workspace {owner.tenant_id}: llm key can't be decrypted" in report.summary()


def test_migration_encrypts_existing_plaintext_keys_and_downgrade_restores_them():
    import asyncio
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.ext.asyncio import create_async_engine

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    tenant_id = uuid.uuid4()

    async def sql(fn):
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                return await fn(conn)
        finally:
            await engine.dispose()

    async def insert(conn):
        # As stored before this change: plain text.
        await conn.execute(sa.insert(Tenant.__table__).values(
            id=tenant_id, name="legacy", llm_config={"model": "m", "api_key": "sk-legacy"},
            embedding_config={"api_key": "sk-legacy-emb"},
        ))

    async def read(conn):
        row = (await conn.execute(sa.select(Tenant.llm_config, Tenant.embedding_config).where(
            Tenant.id == tenant_id
        ))).one()
        return row.llm_config["api_key"], row.embedding_config["api_key"]

    command.downgrade(cfg, "0005")
    try:
        asyncio.run(sql(insert))
        command.upgrade(cfg, "head")
        llm, emb = asyncio.run(sql(read))
        assert llm.startswith("enc:v1:") and emb.startswith("enc:v1:")
        assert (encryption.decrypt(llm), encryption.decrypt(emb)) == ("sk-legacy", "sk-legacy-emb")

        command.downgrade(cfg, "0005")
        assert asyncio.run(sql(read)) == ("sk-legacy", "sk-legacy-emb")
    finally:
        command.upgrade(cfg, "head")
        asyncio.run(sql(lambda conn: conn.execute(sa.delete(Tenant.__table__).where(Tenant.id == tenant_id))))
