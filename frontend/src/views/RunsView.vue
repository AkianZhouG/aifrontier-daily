<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
import type { Run } from '../types'
import { formatDateTime, formatEditionDate, stageLabel, statusLabel, triggerLabel } from '../i18n'

const props = defineProps<{ runs: Run[] }>()
const emit = defineEmits<{ cancel: [string]; retry: [string] }>()
const selected = ref<Run | null>(null)
const logText = ref('')
const loadingLog = ref(false)

async function inspect(run: Run) {
  selected.value = run
  loadingLog.value = true
  try {
    const detail = await api<any>(`/runs/${run.run_id}`)
    const logs = await api<any>(`/runs/${run.run_id}/logs`)
    selected.value = detail
    logText.value = logs.text || '暂无日志'
  } finally {
    loadingLog.value = false
  }
}

function fmt(value?: string) {
  return formatDateTime(value)
}
</script>

<template>
  <div class="view-stack">
    <header class="page-head compact">
      <div><span class="eyebrow">运行记录</span><h1>运行记录</h1><p>每次执行均保留阶段、状态、日志和失败原因。</p></div>
    </header>
    <section class="panel flush">
      <div class="table-scroll">
        <table>
          <thead><tr><th>运行编号</th><th>日报日期</th><th>触发方式</th><th>状态</th><th>进度</th><th>阶段</th><th>开始时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="run in runs" :key="run.run_id">
              <td class="mono">{{ run.run_id }}</td><td>{{ formatEditionDate(run.edition_date) }}</td><td>{{ triggerLabel(run.trigger_type) }}</td>
              <td><span class="run-state" :data-status="run.status">{{ statusLabel(run.status) }}</span></td>
              <td class="mono">{{ Math.round(run.progress_pct) }}%</td><td>{{ stageLabel(run.current_step) }}</td><td>{{ fmt(run.started_at) }}</td>
              <td class="row-actions">
                <button class="text-button" @click="inspect(run)">详情</button>
                <button v-if="['queued','running'].includes(run.status)" class="text-button danger-text" @click="emit('cancel', run.run_id)">取消</button>
                <button v-if="['failed','cancelled'].includes(run.status)" class="text-button" @click="emit('retry', run.run_id)">重试</button>
              </td>
            </tr>
            <tr v-if="!runs.length"><td colspan="8" class="empty-cell">暂无记录</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="selected" class="drawer-backdrop" @click.self="selected = null">
      <aside class="drawer">
        <div class="drawer-head"><div><span class="eyebrow">运行详情</span><h2>{{ selected.run_id }}</h2></div><button class="icon-button" aria-label="关闭" @click="selected = null">×</button></div>
        <dl class="definition-list">
          <div><dt>状态</dt><dd><span class="run-state" :data-status="selected.status">{{ statusLabel(selected.status) }}</span></dd></div>
          <div><dt>阶段</dt><dd>{{ stageLabel(selected.current_step) }}</dd></div>
          <div><dt>开始</dt><dd>{{ fmt(selected.started_at) }}</dd></div>
          <div><dt>结束</dt><dd>{{ fmt(selected.finished_at) }}</dd></div>
        </dl>
        <p v-if="selected.error" class="error-box">{{ selected.error }}</p>
        <h3>阶段账本</h3>
        <ol class="step-ledger">
          <li v-for="step in (selected as any).steps || []" :key="step.step_name"><span>{{ stageLabel(step.step_name) }}</span><strong :data-status="step.status">{{ statusLabel(step.status) }}</strong><small>{{ step.detail }}</small></li>
        </ol>
        <h3>运行日志</h3>
        <pre class="log-view">{{ loadingLog ? '正在加载…' : logText }}</pre>
      </aside>
    </div>
  </div>
</template>
