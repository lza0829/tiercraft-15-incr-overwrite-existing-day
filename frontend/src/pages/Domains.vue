<script setup>
import { onMounted, ref } from 'vue'
import { getJson, putJson } from '../api'

const rows = ref([])
const err = ref('')
const notice = ref('')
const busy = ref(false)
const draft = ref({})

async function refresh() {
  rows.value = await getJson('/api/domains')
  const next = {}
  for (const d of rows.value) next[d.id] = d.load_mode
  draft.value = next
}

onMounted(async () => {
  try {
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

async function saveMode(d) {
  busy.value = true
  err.value = ''
  notice.value = ''
  try {
    const updated = await putJson(`/api/domains/${d.id}/load-mode`, { load_mode: draft.value[d.id] })
    notice.value = `「${updated.name}」装载模式已保存为${updated.load_mode_label}`
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <div>
    <h2>主题域</h2>
    <p class="lead">
      每个主题域对应一套贴源夹具与业务键，并持久化自己的贴源装载模式：增量与全量互斥。
      增量只追加尚未存在的业务日；全量会清空贴源后按夹具重载，并把下游置为待重跑。
    </p>
    <p v-if="err" class="err">{{ err }}</p>
    <p v-if="notice" class="ok-note">{{ notice }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>编号</th><th>名称</th><th>业务键</th><th>夹具文件</th>
            <th>装载模式</th><th>下游状态</th><th>说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in rows" :key="d.id">
            <td>{{ d.id }}</td>
            <td>{{ d.name }}</td>
            <td>{{ d.biz_key }}</td>
            <td>{{ d.fixture_file }}</td>
            <td>
              <select v-model="draft[d.id]" :disabled="busy">
                <option value="incremental">增量</option>
                <option value="full">全量</option>
              </select>
              <button
                class="secondary inline-btn"
                :disabled="busy || draft[d.id] === d.load_mode"
                @click="saveMode(d)"
              >保存</button>
              <div class="muted small">当前：{{ d.load_mode_label }}</div>
            </td>
            <td :class="d.downstream_status === '已对齐' ? 'ok' : 'warn'">{{ d.downstream_status }}</td>
            <td>{{ d.description }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="muted">
      提示：装载入口在「贴源层」与「分层任务」页；模式保存后，下一次装载即按新模式执行。
    </p>
  </div>
</template>
