<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJson } from '../api'
import LoadPanel from '../components/LoadPanel.vue'

const domains = ref([])
const domainId = ref(1)
const rows = ref([])
const dayCounts = ref([])
const jobs = ref([])
const err = ref('')
const notice = ref('')

const current = computed(() => domains.value.find((d) => d.id === domainId.value) || null)

async function refresh() {
  rows.value = await getJson(`/api/layers/贴源?domain_id=${domainId.value}`)
  dayCounts.value = await getJson(`/api/layers/paste/day-counts?domain_id=${domainId.value}`)
  jobs.value = await getJson(`/api/jobs?domain_id=${domainId.value}`)
  const loads = jobs.value.filter((j) => j.step === 'paste_load').slice(0, 5)
  jobs.value = loads
}

async function refreshDomains() {
  domains.value = await getJson('/api/domains')
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

async function onLoaded(job) {
  notice.value = job.status === '成功'
    ? `装载完成：写入 ${job.written_days.length} 日，跳过 ${job.skipped_days.length} 日`
    : ''
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
    <h2>贴源层</h2>
    <p class="lead">尽量保持来源形态入仓，供后续明细清洗使用；装载按主题域保存的模式执行。</p>
    <div class="toolbar">
      <label>
        主题域
        <select v-model.number="domainId" @change="onDomainChange">
          <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
      <span v-if="current" class="muted small">
        下游状态：<b :class="current.downstream_status === '已对齐' ? 'ok' : 'warn'">{{ current.downstream_status }}</b>
      </span>
    </div>

    <LoadPanel
      :domains="domains"
      :domain-id="domainId"
      @loaded="onLoaded"
      @mode-changed="onModeChanged"
      @error="(m) => (err = m)"
    />

    <p v-if="notice" class="ok-note">{{ notice }}</p>
    <p v-if="err && err !== ''" class="err">{{ err }}</p>

    <div class="panel">
      <h3>贴源按业务日计数</h3>
      <table v-if="dayCounts.length">
        <thead><tr><th>业务日</th><th>行数</th><th>门店数</th></tr></thead>
        <tbody>
          <tr v-for="d in dayCounts" :key="d.biz_day">
            <td>{{ d.biz_day }}</td><td>{{ d.rows }}</td><td>{{ d.stores }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">暂无贴源数据，请在上方执行装载。</p>
    </div>

    <div class="panel">
      <h3>最近装载记录</h3>
      <table v-if="jobs.length">
        <thead>
          <tr><th>编号</th><th>模式</th><th>状态</th><th>写入日</th><th>跳过日</th><th>写入行数</th><th>失败原因</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.id">
            <td>{{ j.id }}</td>
            <td>{{ j.mode_label }}</td>
            <td :class="j.status === '成功' ? 'ok' : 'warn'">{{ j.status }}</td>
            <td>{{ j.written_days.length ? j.written_days.join('、') : '—' }}</td>
            <td>{{ j.skipped_days.length ? j.skipped_days.join('、') : '—' }}</td>
            <td>{{ j.out_count }}</td>
            <td class="muted">{{ j.fail_reason || '—' }}</td>
            <td>{{ j.created_at }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">暂无装载记录。</p>
    </div>

    <div class="panel">
      <h3>贴源明细行</h3>
      <table>
        <thead>
          <tr>
            <th>编号</th><th>主题域</th><th>业务日</th><th>门店编码</th><th>门店名称</th>
            <th>品类</th><th>金额</th><th>件数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.domain_id }}</td>
            <td>{{ r.biz_day }}</td>
            <td>{{ r.store_code }}</td>
            <td>{{ r.store_name || '（空）' }}</td>
            <td>{{ r.category }}</td>
            <td>{{ r.amount }}</td>
            <td>{{ r.qty }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length" class="muted">暂无贴源数据。</p>
    </div>
  </div>
</template>
