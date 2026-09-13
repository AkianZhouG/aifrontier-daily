<script setup lang="ts">
import { computed } from 'vue'
import type { Dashboard, Run } from '../types'
import { formatDateTime, formatEditionDate, gitStateLabel, localizedText, stageLabel, statusLabel, timezoneLabel, triggerLabel } from '../i18n'

const props = defineProps<{ dashboard: Dashboard | null; runs: Run[]; busy: boolean }>()
const emit = defineEmits<{ run: []; pause: []; resume: [] }>()

const currentRun = computed(() => props.runs.find(run => ['queued', 'running'].includes(run.status)))
const stages = ['discover', 'fetch', 'extract', 'deduplicate', 'synthesize', 'render', 'commit']

function stageState(stage: string) {
  const run = currentRun.value
  if (!run) return 'idle'
  const index = stages.indexOf(stage)
  const current = stages.indexOf(run.current_step)
  if (run.status === 'failed' && index === current) return 'failed'
  if (index < current || run.status === 'completed') return 'done'
  if (index === current) return 'active'
  return 'idle'
}

function shortTime(value?: string) {
  return formatDateTime(value)
}
</script>

<template>
  <div class="view-stack">
    <header class="page-head">
      <div>
        <span class="eyebrow">控制台</span>
        <h1>日报控制台</h1>
        <p>只收录首次出现或产生实质增量的人工智能前沿事件。</p>
      </div>
      <div class="head-actions">
        <button class="button primary" :disabled="busy || !!currentRun" @click="emit('run')">立即运行</button>
        <button v-if="dashboard?.scheduler.paused" class="button" @click="emit('resume')">恢复调度</button>
        <button v-else class="button" @click="emit('pause')">暂停调度</button>
      </div>
    </header>

    <section class="metric-ledger" aria-label="系统统计">
      <div><strong>{{ dashboard?.counts.sources ?? '--' }}</strong><span>有效来源</span></div>
      <div><strong>{{ dashboard?.counts.events ?? '--' }}</strong><span>事件账本</span></div>
      <div><strong>{{ dashboard?.counts.items ?? '--' }}</strong><span>原始材料</span></div>
      <div><strong>{{ dashboard?.counts.editions ?? '--' }}</strong><span>已出日报</span></div>
      <div :class="{ danger: dashboard?.unhealthy_sources }"><strong>{{ dashboard?.unhealthy_sources ?? '--' }}</strong><span>异常来源</span></div>
    </section>

    <section class="panel pipeline-panel">
      <div class="section-heading">
        <div><span class="eyebrow">处理流程</span><h2>当前流水线</h2></div>
        <div class="mono subtle">{{ currentRun ? `${Math.round(currentRun.progress_pct)}% · ${stageLabel(currentRun.current_step)}` : '空闲' }}</div>
      </div>
      <div class="pipeline-track">
        <div v-for="(stage, index) in stages" :key="stage" class="pipeline-step" :data-state="stageState(stage)">
          <span class="step-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <span>{{ stageLabel(stage) }}</span>
        </div>
      </div>
    </section>

    <div class="split-grid">
      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">调度</span><h2>自动运行</h2></div></div>
        <dl class="definition-list">
          <div><dt>状态</dt><dd><span class="status-dot" :class="dashboard?.scheduler.paused ? 'warn' : 'ok'"></span>{{ dashboard?.scheduler.paused ? '已暂停' : '已启用' }}</dd></div>
          <div><dt>计划</dt><dd>{{ dashboard?.scheduler.schedule ?? '未记录' }} · {{ timezoneLabel(dashboard?.scheduler.timezone) }}</dd></div>
          <div><dt>下次运行</dt><dd>{{ shortTime(dashboard?.scheduler.next_run_time) }}</dd></div>
          <div><dt>当前模型</dt><dd class="mono">{{ dashboard?.agent?.model ?? '未记录' }}</dd></div>
          <div><dt>服务版本</dt><dd class="mono">v{{ dashboard?.service.version ?? '未记录' }} · {{ gitStateLabel(dashboard?.service.git_sha) }}</dd></div>
        </dl>
      </section>

      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">最新一期</span><h2>最近日报</h2></div></div>
        <template v-if="dashboard?.last_edition">
          <div class="edition-date">{{ formatEditionDate(dashboard.last_edition.edition_date) }}</div>
          <p>{{ localizedText(dashboard.last_edition.overview || '日报已生成。') }}</p>
          <a class="text-link" :href="`/api/editions/${dashboard.last_edition.edition_date}/report`" target="_blank">打开日报 ↗</a>
        </template>
        <p v-else class="subtle">还没有日报，可先运行一次测试样例或正式采集。</p>
      </section>
    </div>

    <section class="panel">
      <div class="section-heading"><div><span class="eyebrow">最近任务</span><h2>最近运行</h2></div></div>
      <div class="table-scroll">
        <table>
          <thead><tr><th>运行编号</th><th>触发方式</th><th>状态</th><th>阶段</th><th>开始时间</th></tr></thead>
          <tbody>
            <tr v-for="run in runs.slice(0, 6)" :key="run.run_id">
              <td class="mono">{{ run.run_id }}</td><td>{{ triggerLabel(run.trigger_type) }}</td>
              <td><span class="run-state" :data-status="run.status">{{ statusLabel(run.status) }}</span></td>
              <td>{{ stageLabel(run.current_step) }}</td><td>{{ shortTime(run.started_at) }}</td>
            </tr>
            <tr v-if="!runs.length"><td colspan="5" class="empty-cell">暂无运行记录</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
