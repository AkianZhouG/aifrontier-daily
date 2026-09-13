const statusLabels: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  ready: '已就绪',
  partial: '部分完成',
  draft: '草稿',
  active: '有效',
  ignored: '已忽略',
  candidate: '候选',
  accepted: '已接收',
  duplicate: '重复',
  duplicate_exact: '完全重复',
  duplicate_content: '内容重复',
  insufficient_content: '内容不足',
  quality_rejected: '质量未达标',
  quality_rejected_event: '事件价值未达标',
  editorial_rejected: '未形成实质事件',
  skipped: '已跳过',
  idle: '空闲',
}

const stageLabels: Record<string, string> = {
  starting: '启动',
  discover: '发现',
  fetch: '抓取',
  extract: '提取',
  deduplicate: '去重',
  synthesize: '综合',
  render: '生成',
  commit: '提交',
  done: '完成',
}

const triggerLabels: Record<string, string> = {
  manual: '手动',
  'manual-cli': '命令行手动',
  schedule: '定时',
  catchup: '错过补跑',
  retry: '重试',
  test: '测试',
  'fixture-smoke': '测试样例',
  'initial-bootstrap-final': '首次初始化',
}

const eventTypeLabels: Record<string, string> = {
  release: '发布',
  research: '研究',
  safety: '安全',
  policy: '政策',
  funding: '融资',
  update: '更新',
  news: '资讯',
  benchmark: '评测',
  deployment: '部署',
}

const confidenceLabels: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
}

const sourceKindLabels: Record<string, string> = {
  rss: 'RSS 订阅',
  atom: 'Atom 订阅',
  sitemap: '网站地图',
  github: 'GitHub 搜索',
  fixture: '测试样例',
}

const sourceTierLabels: Record<string, string> = {
  official: '官方来源',
  paper: '论文来源',
  community: '社区来源',
  media: '媒体来源',
}

const claimKeyLabels: Record<string, string> = {
  availability: '可用性',
  capability: '能力',
  benchmark: '基准测试',
  benchmark_availability: '基准测试范围',
  benchmark_optimization_rate: '基准优化复现比例',
  benchmark_result: '基准测试结果',
  benchmark_scope: '基准测试范围',
  price: '价格',
  license: '许可证',
  safety: '安全状态',
  publication_status: '发表状态',
  independently_verified_result: '独立验证结果',
  source_summary: '来源摘要',
  'source-summary': '来源摘要',
  training: '训练方式',
  training_data: '训练数据',
  training_method: '训练方法',
  monitoring: '监测开销',
  analytical_chemistry_result: '分析化学结果',
  architecture: '系统架构',
  capacity_claim: '容量声明',
  capacity_result: '容量结果',
  compatibility: '兼容性',
  computational_cost: '计算成本',
  constructive_result: '构造性结果',
  convergence: '收敛性',
  critic_result: '批评器结果',
  dataset_quality: '数据集质量',
  distributed_benchmark: '分布式基准测试',
  efficiency_claim: '效率声明',
  engineering_result: '工程结果',
  error_record: '错误记录',
  evaluation_scope: '评估范围',
  extensions: '扩展能力',
  function_calling_latency: '函数调用延迟',
  human_contribution: '人工贡献',
  impossibility_result: '不可能性结果',
  integration_status: '集成状态',
  kernel_performance: '内核性能',
  long_horizon_operation: '长时程运行',
  monetization: '商业化',
  output_quality: '输出质量',
  performance: '性能',
  policy_program: '政策项目',
  preview: '预览状态',
  priority_weighted_output: '优先级加权产出',
  privacy_architecture: '隐私架构',
  privacy_availability: '隐私能力可用性',
  protein_design_hit_rate: '蛋白设计命中率',
  protein_target_success: '蛋白靶点成功率',
  reference_reproduction: '参考文本复现',
  runtime_support: '运行支持',
  scalability: '可扩展性',
  scope: '范围',
  storage_tradeoff: '存储权衡',
  task_scope: '任务范围',
  thermal_requirement: '散热要求',
  verification: '验证方式',
}

export function localizedText(value: string | undefined | null): string {
  if (!value) return ''
  const protectedTerms = ['Liquid AI', 'Dharma-AI', 'Hume AI', 'AI with Authority', 'GitHub AI 开源项目']
  const protectedValues: string[] = []
  let text = value
  protectedTerms.forEach(term => {
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    text = text.replace(new RegExp(escaped, 'gi'), match => {
      const token = `\\u0000${protectedValues.length}\\u0000`
      protectedValues.push(match)
      return token
    })
  })
  text = text
    .replace(/Microsoft Research/gi, '微软研究院')
    .replace(/(?<![A-Za-z])Microsoft(?![A-Za-z])/gi, '微软')
    .replace(/NVIDIA Developer Blog/gi, 'NVIDIA 开发者博客')
    .replace(/Hugging Face Blog/gi, 'Hugging Face 博客')
    .replace(/OpenAI News(?: RSS)?/gi, 'OpenAI 官方资讯')
    .replace(/(^|[^A-Za-z.])AI(?![A-Za-z])/g, '$1人工智能')
    .replace(/(?<![A-Za-z])ASR(?![A-Za-z])/gi, '自动语音识别')
    .replace(/(?<![A-Za-z])benchmarks?(?![A-Za-z])/gi, '基准测试')
    .replace(/(?<![A-Za-z])preprints?(?![A-Za-z])/gi, '预印本')
    .replace(/(?<![A-Za-z])claims?(?![A-Za-z])/gi, '事实')
    .replace(/[—–]/g, '，')
  protectedValues.forEach((original, index) => {
    text = text.replace(`\\u0000${index}\\u0000`, original)
  })
  return text
}

export function organizationLabel(value: string | undefined | null): string {
  if (!value) return '未记录'
  const known: Record<string, string> = {
    'Microsoft Research': '微软研究院',
    'IBM Research': 'IBM 研究院',
    'AI with Authority研究团队': 'AI with Authority 研究团队',
  }
  return known[value] || value
}

export function label(value: string | undefined | null, labels: Record<string, string>): string {
  if (!value) return '未记录'
  return labels[value] || value
}

export function statusLabel(value: string | undefined | null): string {
  return label(value, statusLabels)
}

export function stageLabel(value: string | undefined | null): string {
  return label(value, stageLabels)
}

export function triggerLabel(value: string | undefined | null): string {
  return label(value, triggerLabels)
}

export function eventTypeLabel(value: string | undefined | null): string {
  return label(value, eventTypeLabels)
}

export function confidenceLabel(value: string | undefined | null): string {
  return label(value, confidenceLabels)
}

export function sourceKindLabel(value: string | undefined | null): string {
  return label(value, sourceKindLabels)
}

export function sourceTierLabel(value: string | undefined | null): string {
  return label(value, sourceTierLabels)
}

export function claimKeyLabel(value: string | undefined | null): string {
  if (!value) return '其他事实'
  return claimKeyLabels[value] || '其他事实'
}

export function editionStatusLabel(value: string | undefined | null): string {
  return label(value, statusLabels)
}

export function timezoneLabel(value: string | undefined | null): string {
  if (!value) return '未记录'
  if (value === 'Asia/Shanghai') return '中国标准时间（Asia/Shanghai）'
  return value
}

export function gitStateLabel(value: string | undefined | null): string {
  if (value === 'uncommitted') return '未提交'
  if (value === 'unknown') return '未知'
  return value || '未记录'
}

export function formatEditionDate(value?: string): string {
  if (!value) return '未记录'
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  return match ? `${match[1]}年${match[2]}月${match[3]}日` : value
}

export function formatDateTime(value?: string): string {
  if (!value) return '未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(date)
  const part = (type: string) => parts.find(item => item.type === type)?.value || ''
  return `${part('year')}年${part('month')}月${part('day')}日 ${part('hour')}:${part('minute')}:${part('second')}`
}
