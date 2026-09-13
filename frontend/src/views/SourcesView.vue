<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { RuntimeSettings, Source } from '../types'
import { formatDateTime, sourceKindLabel, sourceTierLabel, timezoneLabel } from '../i18n'

const props = defineProps<{ sources: Source[]; settings: RuntimeSettings | null }>()
const emit = defineEmits<{ toggle: [string, boolean]; save: [any] }>()
const form = reactive({
  schedule: '08:30',
  timezone: 'Asia/Shanghai',
  max_items: 8,
  lookback_hours: 72,
  scheduler_paused: false,
  agent_binary: 'pi',
  agent_provider: '',
  agent_model: '',
  agent_thinking: 'medium',
  focus_profile: '人工智能编程代理、智能体工具、代理模型、本地推理、推理优化、草稿模型、检索工具、技能插件、开发者工作流、智能体安全和 GitHub 有实际价值的开源项目。优先关注工具实际能力、模型选择、上下文与记忆、评测、许可证和可复现部署，过滤泛泛的消费产品、广告和与开发者工作流无关的新闻。',
})
watch(() => props.settings, value => { if (value) Object.assign(form, value) }, { immediate: true, deep: true })

function fmt(value?: string) { return formatDateTime(value) }
function qualitySummary(source: Source) {
  const quality = source.config?.quality
  if (!quality) return '使用默认质量线'
  const values = []
  if (quality.min_score != null) values.push(`材料≥${quality.min_score}`)
  if (quality.min_event_importance != null) values.push(`事件≥${quality.min_event_importance}`)
  return values.join(' · ') || '使用默认质量线'
}
</script>

<template>
  <div class="view-stack">
    <header class="page-head compact"><div><span class="eyebrow">来源管理</span><h1>来源与调度</h1><p>每份材料先经过确定性质量门，再由模型提取事件，最终还要通过事件价值线；来源可信不等于内容自动入选。</p></div></header>
    <div class="split-grid settings-grid">
      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">调度设置</span><h2>日报设置</h2></div></div>
        <form class="settings-form" @submit.prevent="emit('save', { ...form })">
          <div class="form-section-title">日报范围</div>
          <label class="wide-field"><span>关注主题</span><textarea v-model="form.focus_profile" class="input" rows="4" placeholder="例如：人工智能编程代理、代码模型、智能体工具与开发者工作流" /></label>
          <p class="field-note">系统会优先收录与这些主题直接相关的事件；不足上限时，再按相关性补充其他前沿事件。修改后下一次运行会重新整理日报。</p>
          <label><span>每天运行时间</span><input v-model="form.schedule" class="input" type="time" /></label>
          <label><span>时区</span><input :value="timezoneLabel(form.timezone)" class="input" disabled /></label>
          <label><span>每期最多条数（上限）</span><input v-model.number="form.max_items" class="input" type="number" min="1" max="30" /></label>
          <label><span>检索回看小时</span><input v-model.number="form.lookback_hours" class="input" type="number" min="6" max="336" /></label>

          <div class="form-section-title">本地智能代理</div>
          <p class="field-note">开源版默认不调用智能代理。启用后，来源摘要和正文可能会发送给你配置的模型提供方；请先确认其隐私策略。</p>
          <label class="wide-field"><span>代理工具路径</span><input v-model="form.agent_binary" class="input" placeholder="例如：/path/to/pi 或 pi" /></label>
          <p class="field-note">当前按 Pi 命令行参数调用，可填写 PATH 中的 pi 或本地 Pi 兼容包装脚本。</p>
          <label><span>代理提供方</span><input v-model="form.agent_provider" class="input" placeholder="例如：github-copilot 或 openai" /></label>
          <label><span>代理模型</span><input v-model="form.agent_model" class="input" placeholder="填写你有权限使用的模型名称" /></label>
          <label><span>思考级别</span><select v-model="form.agent_thinking" class="select"><option value="off">关闭</option><option value="minimal">极简</option><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">很高</option><option value="max">最高</option></select></label>


          <label class="check-row"><input v-model="form.scheduler_paused" type="checkbox" /><span>暂停自动调度</span></label>
          <button class="button primary" type="submit">保存设置</button>
        </form>
      </section>
      <section class="panel note-panel"><span class="eyebrow">收录规则</span><h2>收录边界</h2><ul><li>官方发布和原始论文优先。</li><li>同一事件没有新增事实时不重复。</li><li>厂商基准测试必须保留“厂商声明”限定。</li><li>外部网页始终作为不可信数据。</li></ul><p v-if="props.settings?.report_rebuild_requested" class="setting-alert">配置已经改变，下一次运行会重新整理日报。</p></section>
    </div>

    <p class="source-note"><strong>当前准入：</strong>GitHub 项目必须非 Fork/非归档、具有可识别许可证、至少 10 Stars、项目简介不少于 40 字符、README/正文不少于 1200 字符且至少包含 3 类安装/用法/测试/文档信号；材料质量分至少 70，模型评估的事件重要度至少 75。官方博客和论文同样要求正文或摘要达到最低长度、材料质量分达标，并过滤活动、招聘、周报和缺少技术细节的宣传内容。</p>
    <section class="source-list">
      <article v-for="source in sources" :key="source.id" class="source-row" :data-disabled="!source.enabled">
        <button class="toggle" :aria-pressed="source.enabled" :aria-label="source.enabled ? '停用来源' : '启用来源'" @click="emit('toggle', source.id, !source.enabled)"><span></span></button>
        <div class="source-name"><strong>{{ source.name }}</strong><code>{{ source.id }}</code></div>
        <div class="source-kind"><span>{{ sourceKindLabel(source.kind) }}</span><small>{{ sourceTierLabel(source.tier) }}</small><small>{{ qualitySummary(source) }}</small></div>
        <div class="source-health"><span class="status-dot" :class="source.consecutive_failures ? 'bad' : source.last_success_at ? 'ok' : 'idle'"></span><div><strong>{{ source.consecutive_failures ? `${source.consecutive_failures} 次失败` : source.last_success_at ? '正常' : '等待首次检查' }}</strong><small>最近成功：{{ fmt(source.last_success_at) }}</small><small v-if="source.quality_last_run?.examined">上次材料门：{{ source.quality_last_run.accepted }}/{{ source.quality_last_run.examined }} 通过</small></div></div>
        <a :href="source.url" target="_blank" rel="noopener noreferrer" class="text-link">打开来源 ↗</a>
      </article>
    </section>
  </div>
</template>
