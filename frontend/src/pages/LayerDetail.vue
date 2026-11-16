<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJson } from '../api'

const domains = ref([])
const domainId = ref(1)
const rows = ref([])
const err = ref('')

const current = computed(() => domains.value.find((d) => d.id === domainId.value) || null)
const pending = computed(() => current.value && current.value.downstream_status === '待重跑')

async function refresh() {
  rows.value = await getJson(`/api/layers/明细?domain_id=${domainId.value}`)
}

onMounted(async () => {
  try {
    domains.value = await getJson('/api/domains')
    if (domains.value.length) domainId.value = domains.value[0].id
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

async function onDomainChange() {
  err.value = ''
  try {
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}
</script>
<template>
  <div>
    <h2>明细层</h2>
    <p class="lead">清洗标准化后的明细；门店名为空或金额为负的贴源行不会进入本层。</p>
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
    <p v-if="pending" class="hint warn">
      该主题域贴源已装载但下游尚未重建（可能刚做过全量重载）。当前展示的明细可能属于旧批次，请重跑「贴源到明细」「明细到汇总」。
    </p>
    <p v-if="err" class="err">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>编号</th><th>主题域</th><th>业务日</th><th>门店编码</th><th>门店名称</th>
            <th>品类</th><th>金额</th><th>件数</th><th>清洗标记</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.domain_id }}</td>
            <td>{{ r.biz_day }}</td>
            <td>{{ r.store_code }}</td>
            <td>{{ r.store_name }}</td>
            <td>{{ r.category }}</td>
            <td>{{ r.amount }}</td>
            <td>{{ r.qty }}</td>
            <td>{{ r.clean_flag }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length" class="muted">
        明细层为空{{ pending ? '（全量重载后已清空，待重跑）' : '，请先在「分层任务」执行贴源到明细' }}。
      </p>
    </div>
  </div>
</template>
