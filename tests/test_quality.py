from frontier_daily.pipeline import candidate_fingerprint
from frontier_daily.quality import assess_candidate, source_min_event_importance
from frontier_daily.schemas import CandidateItem, SourceConfig


def github_source() -> SourceConfig:
    return SourceConfig.model_validate(
        {
            "id": "github-ai-open-source",
            "name": "GitHub AI 开源项目",
            "kind": "github",
            "url": "https://api.github.com/search/repositories?q=agent",
            "tier": "community",
            "quality": {
                "min_score": 70,
                "min_event_importance": 75,
                "min_content_chars": 1200,
                "min_stars": 10,
                "min_description_chars": 40,
                "min_documentation_signals": 3,
                "require_license": True,
            },
        }
    )


def github_item(*, stars: int) -> CandidateItem:
    documentation = "\n".join(
        [
            "Installation: pip install useful-agent",
            "Getting Started and Usage",
            "Examples",
            "Tests and Benchmark",
            "Documentation",
            "Deployment",
        ]
    )
    return CandidateItem(
        source_id="github-ai-open-source",
        source_name="GitHub AI 开源项目",
        source_tier="community",
        title="GitHub - example/useful-agent: verifiable tool execution for coding agents",
        url="https://github.com/example/useful-agent",
        published_at="2026-08-26T00:00:00+00:00",
        discovered_at="2026-08-26T01:00:00+00:00",
        summary="A documented agent runtime with reproducible tests and deployment instructions.",
        content=(documentation + "\nConcrete API and security architecture.\n") * 30,
        metadata={
            "repository": {
                "description": "A documented agent runtime with reproducible tests and deployment instructions.",
                "license": "Apache-2.0",
                "stars": stars,
                "forks": 3,
                "topics": ["ai", "agent", "developer-tools"],
            }
        },
    )


def test_github_quality_gate_accepts_documented_project_with_minimum_validation():
    assessment = assess_candidate(github_source(), github_item(stars=14))

    assert assessment.accepted is True
    assert assessment.score >= 70
    assert assessment.documentation_signals >= 3
    assert source_min_event_importance(github_source()) == 75


def test_github_quality_gate_rejects_low_star_project_even_with_long_readme():
    assessment = assess_candidate(github_source(), github_item(stars=4))

    assert assessment.accepted is False
    assert any("Stars 4" in failure for failure in assessment.failures)


def test_github_fingerprint_ignores_star_and_fork_count_changes():
    source = github_source()
    first = github_item(stars=14)
    first.content += "\nStar\n14\nForks\n3 forks\nWatchers\n2 watching"
    second = github_item(stars=99)
    second.content += "\nStar\n99\nForks\n20 forks\nWatchers\n12 watching"

    assert candidate_fingerprint(source, first) == candidate_fingerprint(source, second)


def test_official_quality_gate_rejects_promotional_event():
    source = SourceConfig.model_validate(
        {
            "id": "official-blog",
            "name": "官方博客",
            "kind": "rss",
            "url": "https://example.com/feed.xml",
            "tier": "official",
            "quality": {"min_score": 50, "min_content_chars": 300},
        }
    )
    item = CandidateItem(
        source_id=source.id,
        source_name=source.name,
        source_tier=source.tier,
        title="Register now for our AI webinar",
        url="https://example.com/webinar",
        published_at="2026-08-26T00:00:00+00:00",
        discovered_at="2026-08-26T01:00:00+00:00",
        summary="Join the event.",
        content="This webinar discusses model APIs and deployment. " * 20,
    )

    assessment = assess_candidate(source, item)

    assert assessment.accepted is False
    assert any("低信号" in failure for failure in assessment.failures)
