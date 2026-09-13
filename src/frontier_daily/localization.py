from __future__ import annotations

import re


_PROTECTED_TERMS = (
    re.compile(r"Liquid AI", re.IGNORECASE),
    re.compile(r"Dharma-AI", re.IGNORECASE),
    re.compile(r"Hume AI", re.IGNORECASE),
    re.compile(r"AI with Authority", re.IGNORECASE),
    re.compile(r"GitHub AI 开源项目", re.IGNORECASE),
)

_CLAIM_KEY_LABELS = {
    "availability": "可用性",
    "capability": "能力",
    "benchmark": "基准测试",
    "benchmark_availability": "基准测试范围",
    "benchmark_optimization_rate": "基准优化复现比例",
    "benchmark_result": "基准测试结果",
    "benchmark_scope": "基准测试范围",
    "基准测试_optimization_rate": "基准优化复现比例",
    "基准测试_availability": "基准测试范围",
    "基准测试_result": "基准测试结果",
    "price": "价格",
    "license": "许可证",
    "safety": "安全状态",
    "publication_status": "发表状态",
    "independently_verified_result": "独立验证结果",
    "source_summary": "来源摘要",
    "source-summary": "来源摘要",
    "training": "训练方式",
    "training_data": "训练数据",
    "training_method": "训练方法",
    "monitoring": "监测开销",
    "analytical_chemistry_result": "分析化学结果",
    "architecture": "系统架构",
    "capacity_claim": "容量声明",
    "capacity_result": "容量结果",
    "compatibility": "兼容性",
    "computational_cost": "计算成本",
    "constructive_result": "构造性结果",
    "convergence": "收敛性",
    "critic_result": "批评器结果",
    "dataset_quality": "数据集质量",
    "distributed_benchmark": "分布式基准测试",
    "efficiency_claim": "效率声明",
    "engineering_result": "工程结果",
    "error_record": "错误记录",
    "evaluation_scope": "评估范围",
    "extensions": "扩展能力",
    "function_calling_latency": "函数调用延迟",
    "human_contribution": "人工贡献",
    "impossibility_result": "不可能性结果",
    "integration_status": "集成状态",
    "kernel_performance": "内核性能",
    "long_horizon_operation": "长时程运行",
    "monetization": "商业化",
    "output_quality": "输出质量",
    "performance": "性能",
    "policy_program": "政策项目",
    "preview": "预览状态",
    "priority_weighted_output": "优先级加权产出",
    "privacy_architecture": "隐私架构",
    "privacy_availability": "隐私能力可用性",
    "protein_design_hit_rate": "蛋白设计命中率",
    "protein_target_success": "蛋白靶点成功率",
    "reference_reproduction": "参考文本复现",
    "runtime_support": "运行支持",
    "scalability": "可扩展性",
    "scope": "范围",
    "storage_tradeoff": "存储权衡",
    "task_scope": "任务范围",
    "thermal_requirement": "散热要求",
    "verification": "验证方式",
}

_TERM_REPLACEMENTS = (
    (re.compile(r"(?<![A-Za-z])Microsoft Research(?![A-Za-z])", re.IGNORECASE), "微软研究院"),
    (re.compile(r"(?<![A-Za-z])Microsoft(?![A-Za-z])", re.IGNORECASE), "微软"),
    (re.compile(r"(?<![A-Za-z])NVIDIA Developer Blog(?![A-Za-z])", re.IGNORECASE), "NVIDIA 开发者博客"),
    (re.compile(r"(?<![A-Za-z])Hugging Face Blog(?![A-Za-z])", re.IGNORECASE), "Hugging Face 博客"),
    (re.compile(r"(?<![A-Za-z])OpenAI News(?: RSS)?(?![A-Za-z])", re.IGNORECASE), "OpenAI 官方资讯"),
    (re.compile(r"(?<![A-Za-z.])AI(?![A-Za-z])"), "人工智能"),
    (re.compile(r"(?<![A-Za-z])ASR(?![A-Za-z])", re.IGNORECASE), "自动语音识别"),
    (re.compile(r"(?<![A-Za-z])benchmark(?:s)?(?![A-Za-z])", re.IGNORECASE), "基准测试"),
    (re.compile(r"(?<![A-Za-z])preprints?(?![A-Za-z])", re.IGNORECASE), "预印本"),
    (re.compile(r"(?<![A-Za-z])claims?(?![A-Za-z])", re.IGNORECASE), "事实"),
)


def claim_key_label(value: str | None) -> str:
    return _CLAIM_KEY_LABELS.get(str(value or "").strip().lower(), "其他事实")


def localize_claim_text(value: str) -> str:
    text = str(value or "").strip()
    match = re.match(r"^([^:\s]+)\s*:\s*(.*)$", text, re.DOTALL)
    if not match:
        return clean_chinese_text(text)
    return f"{claim_key_label(match.group(1))}：{clean_chinese_text(match.group(2))}"


def clean_chinese_text(value: str) -> str:
    """Normalize model prose for the Chinese-facing report and interface."""

    text = re.sub(
        r"(\d+(?:\.\d+)?%?)[—–](\d+(?:\.\d+)?%?)",
        r"\1 至 \2",
        str(value or ""),
    )
    text = text.replace("—", "，").replace("–", "，")
    protected: dict[str, str] = {}

    def stash(match: re.Match[str]) -> str:
        token = f"\x00{len(protected)}\x00"
        protected[token] = match.group(0)
        return token

    for pattern in _PROTECTED_TERMS:
        text = pattern.sub(stash, text)
    for pattern, replacement in _TERM_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    for token, original in protected.items():
        text = text.replace(token, original)
    return text
