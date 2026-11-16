<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJson, postJson } from '../api'
import LoadPanel from '../components/LoadPanel.vue'

const domains = ref([])
const domainId = ref(1)
const jobs = ref([])
const err = ref('')
const notice = ref('')
const busy = ref(false)

const current = computed(() => domains.value.find((d) => d.id === domainId.value) || null)

async function refreshDomains() {
  domains.value = await getJson('/api/domains')
}

async function refresh() {
  jobs.value = await getJson(`/api/jobs?domain_id=${domainId.value}`)
}

onMounted(async () => {
  try {
    await refreshDomains()
    if (domains.value.length) domainId.value = domains.value[0].id
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

async function onDomainChange() {
  err.value = ''
  notice.value = ''
  try {
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function run(step) {
  busy.value = true
  err.value = ''
  notice.value = ''
  try {
    const url = step === '明细'
      ? '/api/jobs/paste-to-detail'
      : '/api/jobs/detail-to-summary'
    await postJson(url, { domain_id: domainId.value })
    await refreshDomains()
    await refresh()
    notice.value = step === '明细' ? '贴源到明细已完成' : '明细到汇总已完成'
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function onLoaded(job) {
  notice.value = job && job.status === '成功' ? '贴源装载完成' : ''
  err.value = ''
  try {
    await refreshDomains()
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function onModeChanged() {
  try {
    await refreshDomains()
  } catch (e) {
    err.value = String(e.message || e)
  }
}
</script>
<template>
  <div>
    <h2>分层任务</h2>
    <p class="lead">
      按主题域推进：先按装载模式装载贴源，再贴源到明细，最后明细到汇总。
      每次装载都会留下模式、写入日、跳过日、写入行数与失败原因。
    </p>
    <div class="toolbar">
      <label>
        主题域
        <select v-model.number="domainId" @change="onDomainChange">
          <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
      <span v-if="current" class="muted small">
        当前模式：<b>{{ current.load_mode_label }}</b>
        · 下游：<b :class="current.downstream_status === '已对齐' ? 'ok' : 'warn'">{{ current.downstream_status }}</b>
      </span>
    </div>

    <LoadPanel
      :domains="domains"
      :domain-id="domainId"
      @loaded="onLoaded"
      @mode-changed="onModeChanged"
      @error="(m) => (err = m)"
    />

    <div class="toolbar">
      <button :disabled="busy" @click="run('明细')">跑贴源到明细</button>
      <button class="secondary" :disabled="busy" @click="run('汇总')">跑明细到汇总</button>
    </div>
    <p v-if="notice" class="ok-note">{{ notice }}</p>
    <p v-if="err" class="err">{{ err }}</p>

    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>编号</th><th>步骤</th><th>模式</th><th>状态</th><th>说明</th>
            <th>写入日</th><th>跳过日</th><th>输入</th><th>写入</th><th>剔除</th>
            <th>失败原因</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.id">
            <td>{{ j.id }}</td>
            <td>{{ j.step_label || j.step }}</td>
            <td>{{ j.step === 'paste_load' ? j.mode_label : '—' }}</td>
            <td :class="j.status === '成功' ? 'ok' : 'warn'">{{ j.status }}</td>
            <td>{{ j.message }}</td>
            <td>{{ j.written_days && j.written_days.length ? j.written_days.join('、') : '—' }}</td>
            <td>{{ j.skipped_days && j.skipped_days.length ? j.skipped_days.join('、') : '—' }}</td>
            <td>{{ j.in_count }}</td>
            <td>{{ j.out_count }}</td>
            <td>{{ j.drop_count }}</td>
            <td class="muted">{{ j.fail_reason || '—' }}</td>
            <td>{{ j.created_at }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!jobs.length" class="muted">还没有任务记录。</p>
    </div>
  </div>
</template>
