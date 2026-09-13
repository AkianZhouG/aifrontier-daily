<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, initializeSession } from './api'
import type { Dashboard, Edition, EventRecord, Run, RuntimeSettings, Source } from './types'
import OverviewView from './views/OverviewView.vue'
import RunsView from './views/RunsView.vue'
import EventsView from './views/EventsView.vue'
import ReportsView from './views/ReportsView.vue'
import SourcesView from './views/SourcesView.vue'

const active = ref('overview')
const dashboard = ref<Dashboard | null>(null)
const runs = ref<Run[]>([])
const events = ref<EventRecord[]>([])
const editions = ref<Edition[]>([])
const sources = ref<Source[]>([])
const settings = ref<RuntimeSettings | null>(null)
const busy = ref(false)
const error = ref('')
const notice = ref('')
let stream: EventSource | null = null
let noticeTimer: number | null = null

const nav = [
  { id: 'overview', label: '总览', index: '01' },
  { id: 'runs', label: '运行', index: '02' },
  { id: 'events', label: '事件账本', index: '03' },
  { id: 'reports', label: '日报', index: '04' },
  { id: 'sources', label: '来源与调度', index: '05' },
]

function toast(message: string) {
  notice.value = message
  if (noticeTimer) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => (notice.value = ''), 3200)
}

async function refreshAll() {
  const [d, r, e, ed, s, st] = await Promise.all([
    api<Dashboard>('/dashboard'), api<Run[]>('/runs?limit=50'), api<EventRecord[]>('/events?limit=200'),
    api<Edition[]>('/editions?limit=50'), api<Source[]>('/sources'), api<RuntimeSettings>('/settings'),
  ])
  dashboard.value = d; runs.value = r; events.value = e; editions.value = ed; sources.value = s; settings.value = st
}

async function action(task: () => Promise<any>, success: string) {
  busy.value = true; error.value = ''
  try { await task(); toast(success); await refreshAll() }
  catch (cause: any) { error.value = cause?.message || String(cause) }
  finally { busy.value = false }
}

function runNow() { return action(() => api('/runs', { method: 'POST', body: JSON.stringify({ no_llm: false }) }), '日报任务已启动') }
function cancelRun(id: string) { return action(() => api(`/runs/${id}/cancel`, { method: 'POST' }), '取消请求已发送') }
function retryRun(id: string) { return action(() => api(`/runs/${id}/retry`, { method: 'POST' }), '任务已重新排队') }
function pause() { return action(() => api('/scheduler/pause', { method: 'POST' }), '自动调度已暂停') }
function resume() { return action(() => api('/scheduler/resume', { method: 'POST' }), '自动调度已恢复') }
function eventAction(id: number, value: 'ignore'|'restore'|'force-next') { return action(() => api(`/events/${id}/action`, { method: 'POST', body: JSON.stringify({ action: value }) }), '事件状态已更新') }
function toggleSource(id: string, enabled: boolean) { return action(() => api(`/sources/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }), enabled ? '来源已启用' : '来源已停用') }
function saveSettings(value: any) { return action(() => api('/settings', { method: 'PUT', body: JSON.stringify(value) }), '设置已保存，下次运行将应用新的代理与关注主题') }

function connectStream() {
  stream = new EventSource('/api/stream')
  stream.addEventListener('state', (message: MessageEvent) => {
    const value = JSON.parse(message.data)
    dashboard.value = { ...(dashboard.value || {}), ...value.dashboard, scheduler: value.scheduler } as Dashboard
    runs.value = value.runs
  })
  stream.onerror = () => { stream?.close(); window.setTimeout(connectStream, 5000) }
}

onMounted(async () => {
  try { await initializeSession(); await refreshAll(); connectStream() }
  catch (cause: any) { error.value = cause?.message || String(cause) }
})
onUnmounted(() => { stream?.close(); if (noticeTimer) window.clearTimeout(noticeTimer) })
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">前沿</span><div><strong>人工智能前沿日报</strong><small>本机智能简报</small></div></div>
      <nav aria-label="主导航">
        <button v-for="item in nav" :key="item.id" :class="{ active: active === item.id }" @click="active = item.id"><span>{{ item.index }}</span>{{ item.label }}</button>
      </nav>
      <div class="sidebar-foot">
        <span class="status-dot" :class="dashboard ? 'ok' : 'bad'"></span>
        <div><strong>{{ dashboard ? '本机服务在线' : '正在连接' }}</strong><small>仅本机 · 127.0.0.1:8787</small></div>
      </div>
    </aside>
    <main class="content">
      <div v-if="error" class="alert"><span>{{ error }}</span><button @click="error = ''">×</button></div>
      <OverviewView v-if="active === 'overview'" :dashboard="dashboard" :runs="runs" :busy="busy" @run="runNow" @pause="pause" @resume="resume" />
      <RunsView v-else-if="active === 'runs'" :runs="runs" @cancel="cancelRun" @retry="retryRun" />
      <EventsView v-else-if="active === 'events'" :events="events" @action="eventAction" />
      <ReportsView v-else-if="active === 'reports'" :editions="editions" />
      <SourcesView v-else :sources="sources" :settings="settings" @toggle="toggleSource" @save="saveSettings" />
    </main>
    <div v-if="notice" class="toast">{{ notice }}</div>
  </div>
</template>
