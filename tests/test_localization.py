from frontier_daily.localization import clean_chinese_text, localize_claim_text


def test_clean_chinese_text_localizes_common_terms_and_ranges():
    value = clean_chinese_text("AI benchmark results from Microsoft Research: 18%—30%")
    assert value == "人工智能 基准测试 results from 微软研究院: 18% 至 30%"
    assert "—" not in value
    assert "–" not in value
    assert localize_claim_text("benchmark_result: AI score") == "基准测试结果：人工智能 score"
    assert localize_claim_text("unknown_key: value") == "其他事实：value"
    assert clean_chinese_text("GitHub AI 开源项目") == "GitHub AI 开源项目"
