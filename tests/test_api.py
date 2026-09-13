import sys

from fastapi.testclient import TestClient

from frontier_daily.api import create_app


def test_local_control_requires_csrf_for_mutations(app_config):
    app = create_app(app_config)
    with TestClient(app, base_url="http://testserver") as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        blocked = client.patch("/api/sources/arxiv-ai", json={"enabled": False})
        assert blocked.status_code == 403

        session = client.get("/api/session")
        token = session.json()["csrf_token"]
        response = client.patch(
            "/api/sources/arxiv-ai",
            json={"enabled": False},
            headers={"Origin": "http://testserver", "X-Frontier-CSRF": token},
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is False


def test_sources_expose_quality_policy_and_latest_gate_counts(app_config):
    app = create_app(app_config)
    with TestClient(app, base_url="http://testserver") as client:
        sources = client.get("/api/sources").json()

    github = next(source for source in sources if source["id"] == "github-ai-open-source")
    assert github["config"]["quality"]["min_stars"] == 10
    assert github["config"]["quality"]["min_event_importance"] == 75
    assert github["quality_last_run"] == {
        "examined": 0,
        "accepted": 0,
        "rejected": 0,
        "unassessed": 0,
    }


def test_dashboard_exposes_durable_counts(app_config):
    app = create_app(app_config)
    with TestClient(app, base_url="http://testserver") as client:
        payload = client.get("/api/dashboard").json()
        assert payload["counts"]["sources"] >= 1
        assert payload["scheduler"]["schedule"] == "23:59"
        assert payload["agent"]["model"] == app_config.pi_model


def test_settings_exposes_agent_and_focus_configuration(app_config):
    app = create_app(app_config)
    with TestClient(app, base_url="http://testserver") as client:
        payload = client.get("/api/settings").json()
        assert payload["agent_model"] == app_config.pi_model
        assert payload["agent_binary"]
        assert payload["focus_profile"]
        assert "report_rebuild_requested" in payload


def test_settings_can_update_without_optional_agent(app_config):
    app = create_app(app_config)
    with TestClient(app, base_url="http://testserver") as client:
        session = client.get("/api/session")
        token = session.json()["csrf_token"]
        response = client.put(
            "/api/settings",
            json={
                "schedule": "07:30",
                "timezone": app_config.timezone,
                "max_items": 8,
                "lookback_hours": 72,
                "scheduler_paused": False,
                "agent_binary": "pi",
                "agent_provider": "",
                "agent_model": "",
                "agent_thinking": "medium",
                "focus_profile": "本地日报",
            },
            headers={"Origin": "http://testserver", "X-Frontier-CSRF": token},
        )
        assert response.status_code == 200
        assert response.json()["schedule"] == "07:30"
        assert response.json()["agent_model"] == app_config.pi_model


def test_settings_updates_agent_and_focus_profile(app_config):
    app = create_app(app_config)
    with TestClient(app, base_url="http://testserver") as client:
        session = client.get("/api/session")
        token = session.json()["csrf_token"]
        response = client.put(
            "/api/settings",
            json={
                "schedule": "23:59",
                "timezone": app_config.timezone,
                "max_items": 8,
                "lookback_hours": 72,
                "scheduler_paused": False,
                "agent_binary": sys.executable,
                "agent_provider": "local-provider",
                "agent_model": "local-model",
                "agent_thinking": "medium",
                "focus_profile": "本地编程代理和模型",
            },
            headers={"Origin": "http://testserver", "X-Frontier-CSRF": token},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["agent_model"] == "local-model"
        assert payload["agent_thinking"] == "medium"
        assert payload["focus_profile"] == "本地编程代理和模型"
        assert payload["report_rebuild_requested"] is True


def test_report_disables_http_cache_after_rerun(app_config):
    app = create_app(app_config)
    edition_date = "2026-08-26"
    json_path = app_config.artifacts_dir / edition_date / "edition.json"
    html_path = app_config.artifacts_dir / edition_date / "report.html"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text("{}", encoding="utf-8")
    html_path.write_text("<p>fresh report</p>", encoding="utf-8")
    app.state.db.upsert_edition_draft(edition_date)
    app.state.db.commit_edition(
        edition_date=edition_date,
        status="ready",
        title="测试日报",
        overview="测试",
        json_path=json_path,
        html_path=html_path,
        events=[],
    )

    with TestClient(app, base_url="http://testserver") as client:
        response = client.get(f"/api/editions/{edition_date}/report")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.text == "<p>fresh report</p>"
