from datetime import datetime

import pytest

from frontier_daily.pipeline import Pipeline, PipelineError


def test_all_source_failures_do_not_publish_empty_ready_edition(app_config, db, monkeypatch):
    run_id = db.create_run(
        trigger_type="test",
        edition_date=datetime.now(app_config.tz).date().isoformat(),
        log_path=app_config.logs_dir / "source-failure.log",
    )

    def fail_collect(_source):
        raise OSError("DNS unavailable")

    monkeypatch.setattr("frontier_daily.pipeline.get_collector", fail_collect)
    with pytest.raises(PipelineError, match="全部采集失败"):
        Pipeline(app_config, db, run_id).run_pipeline()

    edition = db.edition_for_date(datetime.now(app_config.tz).date().isoformat())
    assert edition is not None
    assert edition["status"] == "failed"
    assert edition["items"] == []


def test_fixture_pipeline_is_idempotent(app_config, db):
    fixture = app_config.root / "tests" / "fixtures" / "frontier-items.json"
    edition_date = datetime.now(app_config.tz).date().isoformat()
    run1 = db.create_run(
        trigger_type="test",
        edition_date=edition_date,
        log_path=app_config.logs_dir / "run1.jsonl",
        fixture_path=str(fixture),
        no_llm=True,
    )
    result1 = Pipeline(app_config, db, run1).run_pipeline()
    assert result1["status"] == "partial"
    edition1 = db.edition_for_date(edition_date)
    assert edition1 is not None
    assert edition1["status"] == "partial"
    assert len(edition1["items"]) == 2
    report = app_config.artifacts_dir / edition_date / "report.html"
    assert report.is_file()
    report_text = report.read_text(encoding="utf-8")
    assert "—" not in report_text
    assert "–" not in report_text
    assert "人工智能前沿日报" in report_text
    assert "发布时间：2026年08月24日" in report_text
    assert "来源摘要：" in report_text

    run2 = db.create_run(
        trigger_type="test",
        edition_date=edition_date,
        log_path=app_config.logs_dir / "run2.jsonl",
        fixture_path=str(fixture),
        no_llm=True,
    )
    result2 = Pipeline(app_config, db, run2).run_pipeline()
    assert result2["status"] == "unchanged"
    edition2 = db.edition_for_date(edition_date)
    assert len(edition2["items"]) == 2
