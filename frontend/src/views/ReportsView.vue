<script setup lang="ts">
import { ref } from 'vue'
import type { Edition } from '../types'
import { editionStatusLabel, formatEditionDate, localizedText } from '../i18n'

const props = defineProps<{ editions: Edition[] }>()
const selected = ref<string | null>(null)
function open(date: string) { selected.value = date }
</script>

<template>
  <div class="view-stack">
    <header class="page-head compact"><div><span class="eyebrow">日报归档</span><h1>日报归档</h1><p>每期日报对应一组不可重复的事件和新增事实。</p></div></header>
    <section class="edition-list">
      <article v-for="edition in props.editions" :key="edition.edition_date" class="edition-row">
        <time>{{ formatEditionDate(edition.edition_date) }}</time>
        <div><strong>{{ localizedText(edition.title || `人工智能前沿日报 · ${formatEditionDate(edition.edition_date)}`) }}</strong><p>{{ localizedText(edition.overview || '暂无摘要') }}</p></div>
        <span class="edition-count">{{ edition.item_count }} 条</span>
        <span class="run-state" :data-status="edition.status === 'ready' ? 'completed' : edition.status">{{ editionStatusLabel(edition.status) }}</span>
        <button class="button small" @click="open(edition.edition_date)">预览</button>
      </article>
      <div v-if="!props.editions.length" class="empty-state">还没有日报。</div>
    </section>
    <div v-if="selected" class="report-preview">
      <div class="report-preview-head"><div><span class="eyebrow">日报预览</span><strong>{{ formatEditionDate(selected || undefined) }}</strong></div><div class="row-actions"><a class="button small" :href="`/api/editions/${selected}/report`" target="_blank">在新窗口打开</a><button class="icon-button" aria-label="关闭预览" @click="selected = null">×</button></div></div>
      <iframe :src="`/api/editions/${selected}/report`" title="日报预览"></iframe>
    </div>
  </div>
</template>
