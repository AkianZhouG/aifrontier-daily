<script setup lang="ts">
import { computed, ref } from 'vue'
import type { EventRecord } from '../types'
import { claimKeyLabel, confidenceLabel, eventTypeLabel, formatDateTime, formatEditionDate, localizedText, organizationLabel } from '../i18n'

const props = defineProps<{ events: EventRecord[] }>()
const emit = defineEmits<{ action: [number, 'ignore' | 'restore' | 'force-next'] }>()
const query = ref('')
const status = ref<'all' | 'active' | 'ignored'>('all')
const expanded = ref<number | null>(null)

const filtered = computed(() => props.events.filter(event => {
  if (status.value !== 'all' && event.status !== status.value) return false
  const needle = query.value.trim().toLowerCase()
  if (!needle) return true
  return `${event.title_zh} ${event.entity} ${event.subject} ${event.event_key}`.toLowerCase().includes(needle)
}))

function date(value?: string) {
  return formatDateTime(value)
}
</script>

<template>
  <div class="view-stack">
    <header class="page-head compact">
      <div><span class="eyebrow">事件账本</span><h1>事件去重账本</h1><p>同一事件聚合多来源，只在产生实质增量时再次进入日报。</p></div>
    </header>
    <div class="toolbar">
      <input v-model="query" class="input" placeholder="搜索机构、产品或事件标识" aria-label="搜索事件" />
      <select v-model="status" class="select" aria-label="事件状态"><option value="all">全部状态</option><option value="active">有效</option><option value="ignored">已忽略</option></select>
      <span class="toolbar-count">{{ filtered.length }} 条</span>
    </div>

    <section class="event-ledger">
      <article v-for="event in filtered" :key="event.id" class="event-row" :data-muted="event.status === 'ignored'">
        <button class="event-main" @click="expanded = expanded === event.id ? null : event.id">
          <span class="importance mono">{{ event.importance }}</span>
          <span class="event-copy"><strong>{{ localizedText(event.title_zh) }}</strong><small>{{ organizationLabel(event.entity) }} · {{ eventTypeLabel(event.event_type) }} · 置信度{{ confidenceLabel(event.confidence) }}</small></span>
          <span class="event-meta"><small>{{ event.source_count }} 个来源 · {{ event.claim_count }} 条关键事实</small><small>{{ event.last_edition ? `日报 ${formatEditionDate(event.last_edition)}` : '尚未出刊' }}</small></span>
          <span class="chevron">{{ expanded === event.id ? '−' : '+' }}</span>
        </button>
        <div v-if="expanded === event.id" class="event-detail">
          <div><span class="eyebrow">事件标识</span><code>{{ event.event_key }}</code></div>
          <p>{{ localizedText(event.summary_zh) }}</p>
          <p class="subtle">{{ localizedText(event.why_it_matters_zh) }}</p>
          <ul v-if="event.claims.length" class="claim-list"><li v-for="claim in event.claims" :key="claim.claim_key + claim.claim_value"><strong>{{ claimKeyLabel(claim.claim_key) }}</strong>{{ localizedText(claim.claim_value) }}</li></ul>
          <p v-else class="subtle">暂无关键事实记录。</p>
          <div class="event-foot"><a v-if="event.source_url" :href="event.source_url" target="_blank" rel="noopener noreferrer">查看来源：{{ localizedText(event.source_name) }} ↗</a><span>首次发现 {{ date(event.first_seen_at) }} · 最近发现 {{ date(event.last_seen_at) }}</span></div>
          <div class="row-actions">
            <button v-if="event.status === 'active'" class="button small" @click="emit('action', event.id, 'ignore')">忽略事件</button>
            <button v-else class="button small" @click="emit('action', event.id, 'restore')">恢复事件</button>
            <button class="button small" @click="emit('action', event.id, 'force-next')">强制进入下一期</button>
          </div>
        </div>
      </article>
      <div v-if="!filtered.length" class="empty-state">没有匹配的事件。</div>
    </section>
  </div>
</template>
