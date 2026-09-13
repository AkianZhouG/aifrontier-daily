from pathlib import Path

from frontier_daily.schemas import ExtractedClaim, ExtractedEvent


def add_item(db, run_id: str, suffix: str = "one") -> int:
    item_id, _ = db.add_source_item(
        run_id=run_id,
        source_id="openai-rss",
        url=f"https://openai.com/index/{suffix}",
        canonical_url=f"https://openai.com/index/{suffix}",
        title="Astra safety update",
        published_at="2026-08-24T08:00:00+08:00",
        discovered_at="2026-08-24T09:00:00+08:00",
        summary="Training paused",
        content="Training paused for stronger monitoring",
        content_hash=f"hash-{suffix}",
    )
    return item_id


def make_run(db, app_config, suffix: str) -> str:
    return db.create_run(
        trigger_type="test",
        edition_date=f"2026-08-{suffix}",
        log_path=app_config.logs_dir / f"{suffix}.log",
    )


def test_event_is_new_then_duplicate_then_material_update(db, app_config):
    run1 = make_run(db, app_config, "22")
    item1 = add_item(db, run1, "one")
    base = ExtractedEvent(
        event_key="openai|astra|safety",
        entity="OpenAI",
        subject="Astra",
        event_type="safety",
        title_zh="Astra 安全更新",
        summary_zh="训练暂缓。",
        why_it_matters_zh="安全开始影响训练节奏。",
        importance=90,
        confidence="high",
        source_item_ids=[item1],
        claims=[ExtractedClaim(key="training", value="frontier RL paused")],
    )
    _, decision, delta = db.upsert_event(run1, base)
    assert decision == "new"
    assert delta == ["训练方式：frontier RL paused"]

    db.update_run(run1, status="completed")
    drift_run = make_run(db, app_config, "21")
    same_item = add_item(db, drift_run, "one")
    drifted = base.model_copy(deep=True)
    drifted.event_key = "openai|frontier-training|safety-update"
    drifted.source_item_ids = [same_item]
    _, decision, _ = db.upsert_event(drift_run, drifted)
    assert decision == "duplicate"
    assert len(db.list_events()) == 1

    db.update_run(drift_run, status="completed")
    run2 = make_run(db, app_config, "23")
    item2 = add_item(db, run2, "two")
    duplicate = base.model_copy(deep=True)
    duplicate.source_item_ids = [item2]
    _, decision, delta = db.upsert_event(run2, duplicate)
    assert decision == "duplicate"
    assert delta == []

    db.update_run(run2, status="completed")
    run3 = make_run(db, app_config, "24")
    item3 = add_item(db, run3, "three")
    update = base.model_copy(deep=True)
    update.source_item_ids = [item3]
    update.claims.append(ExtractedClaim(key="monitoring", value="20% compute overhead"))
    _, decision, delta = db.upsert_event(run3, update)
    assert decision == "update"
    assert "监测开销：20% compute overhead" in delta
