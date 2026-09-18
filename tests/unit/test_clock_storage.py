"""Tests: klok + opslag + logging-redactie."""

import json
from datetime import datetime, timedelta, timezone

from wekker.clock import FakeClock
from wekker.logging_config import redact
from wekker.storage import JsonStore


def _start():
    return datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)


def test_fakeclock_verplicht_tz_aware():
    import pytest

    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 1, 1, 0, 0))
    klok = FakeClock(_start())
    assert klok.now() == _start()
    klok.advance(timedelta(minutes=5))
    assert klok.now() == _start() + timedelta(minutes=5)


def test_jsonstore_roundtrip_en_missing(tmp_path):
    store = JsonStore(tmp_path / "sub" / "settings.json")
    assert store.load() is None
    store.save({"alarm": {"time": "07:00"}})
    assert store.load() == {"alarm": {"time": "07:00"}}
    # geen halve bestanden: valide JSON
    assert json.loads((tmp_path / "sub" / "settings.json").read_text())


def test_jsonstore_corrupt_geeft_fout(tmp_path):
    from wekker.storage import StorageError

    p = tmp_path / "s.json"
    p.write_text("{ongeldig", encoding="utf-8")
    import pytest

    with pytest.raises(StorageError):
        JsonStore(p).load()


def test_redact_maskeert_geheimen():
    assert redact("password=geheim123") == "password=***"
    assert redact("token: abcdef") == "token: ***"
    assert redact("Bearer abc.DEF-123") == "Bearer ***"
    # normale tekst blijft staan
    assert redact("alarm om 07:30") == "alarm om 07:30"
