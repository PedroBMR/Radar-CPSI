"""Testes da deduplicação e do armazenamento SQLite."""

from __future__ import annotations

import pytest

from radar_cpsi.database import Database
from radar_cpsi.models import Edital


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def make_edital(**overrides) -> Edital:
    base = dict(
        source="pncp",
        title="Edital CPSI videomonitoramento",
        link="https://pncp.gov.br/app/editais/x/2025/1",
        native_id="00000000000191-1-000001/2025",
    )
    base.update(overrides)
    return Edital(**base)


def test_dedup_key_uses_native_id():
    e1 = make_edital()
    e2 = make_edital(title="Título diferente", link="https://outro.link")
    # mesmo native_id -> mesma chave
    assert e1.dedup_key == e2.dedup_key


def test_dedup_key_falls_back_to_link_and_title():
    e1 = make_edital(native_id=None)
    e2 = make_edital(native_id=None, title="Outro")
    assert e1.dedup_key != e2.dedup_key


def test_insert_new_then_duplicate(db):
    e = make_edital()
    assert db.insert_edital(e) is True     # primeiro insert é novo
    assert db.insert_edital(e) is False    # segundo é duplicado
    assert db.count() == 1


def test_duplicate_across_different_objects_same_id(db):
    assert db.insert_edital(make_edital()) is True
    # outro objeto, mesmo native_id, título/descrição diferentes
    dup = make_edital(title="Republicação", descricao="texto novo")
    assert db.insert_edital(dup) is False
    assert db.count() == 1


def test_backfill_records_are_pre_notified(db):
    e = make_edital(origem="backfill")
    db.insert_edital(e)
    # backfill não deve aparecer como notificação pendente
    assert db.pending_notifications() == []


def test_daily_records_are_pending(db):
    e = make_edital(origem="diario")
    db.insert_edital(e)
    pending = db.pending_notifications()
    assert len(pending) == 1
    db.mark_notified(pending[0]["id"])
    assert db.pending_notifications() == []


def test_origem_counts(db):
    db.insert_edital(make_edital(native_id="a", origem="diario"))
    db.insert_edital(make_edital(native_id="b", origem="backfill"))
    db.insert_edital(make_edital(native_id="c", origem="backfill"))
    assert db.count(origem="diario") == 1
    assert db.count(origem="backfill") == 2
    assert db.count() == 3


def test_source_health_alert_threshold(db):
    for _ in range(2):
        db.record_source_failure("pncp", "erro X")
    assert not db.should_alert_source("pncp", threshold=3)
    db.record_source_failure("pncp", "erro X")
    assert db.should_alert_source("pncp", threshold=3)
    db.mark_source_alerted("pncp")
    assert not db.should_alert_source("pncp", threshold=3)
    # recuperação zera o contador
    db.record_source_ok("pncp")
    assert not db.should_alert_source("pncp", threshold=3)
