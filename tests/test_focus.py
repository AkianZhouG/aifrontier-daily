from frontier_daily.pipeline import Pipeline, focus_score


def test_focus_score_prefers_agent_and_excludes_generic_science_news():
    profile = "人工智能编程代理、智能体工具、代理模型、本地推理、草稿模型、检索工具、技能插件"
    assert focus_score({"title_zh": "智能体记忆和上下文注入"}, profile) > 0
    assert focus_score({"title_zh": "生命科学视觉基准测试", "summary_zh": "湿实验图像评测"}, profile) == 0


def test_focus_rebuild_fills_remaining_slots_with_related_events(app_config):
    class FakeDB:
        def edition_for_date(self, edition_date):
            return None

        def list_events(self, limit, status):
            return [
                {"id": 1, "title_zh": "智能体记忆策略", "importance": 40, "last_seen_at": "2"},
                {"id": 2, "title_zh": "生命科学视觉评测", "importance": 90, "last_seen_at": "1"},
                {"id": 3, "title_zh": "代码模型工具", "importance": 30, "last_seen_at": "0"},
            ]

        def get_setting(self, key, default=None):
            return 20 if key == "max_items" else "智能体、代码模型和工具"

    pipeline = object.__new__(Pipeline)
    pipeline.db = FakeDB()
    pipeline.config = app_config
    selected = pipeline._combine_with_existing_edition([], "2026-08-24", rebuild_focus=True)

    assert len(selected) == 3
    assert [item["decision"] for item in selected] == ["focus", "focus", "related"]
