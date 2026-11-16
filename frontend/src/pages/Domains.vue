<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJson, putJson } from '../api'

const rows = ref([])
const verdicts = ref([])
const err = ref('')
const notice = ref('')
const busy = ref(false)
const draft = ref({})

const latestVerdict = computed(() => {
  // /load-verdicts 按 id 倒序返回，每个主题域的第一条即最近一次装载裁决证明。
  const map = {}
  for (const v of verdicts.value) {
    if (!map[v.domain_id]) map[v.domain_id] = v
  }
  return map
})

async function refresh() {
  rows.value = await getJson('/api/domains')
  verdicts.value = await getJson('/api/load-verdicts')
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
            <th>装载模式</th><th>下游状态</th><th>最近装载裁决证明</th><th>说明</th>
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
            <td>
              <template v-if="latestVerdict[d.id]">
                <div class="muted small">
                  模式：{{ latestVerdict[d.id].load_mode_label }}
                </div>
                <div class="muted small">
                  写入日：{{ latestVerdict[d.id].written_days.length
                    ? latestVerdict[d.id].written_days.join('、') : '无' }}
                </div>
                <div class="muted small">
                  跳过日：<span :class="latestVerdict[d.id].skipped_days.length ? 'warn' : ''">
                    {{ latestVerdict[d.id].skipped_days.length
                      ? latestVerdict[d.id].skipped_days.join('、') : '无' }}
                  </span>
                </div>
                <div class="small">
                  下游：
                  <b :class="latestVerdict[d.id].downstream_pending ? 'warn' : 'ok'">
                    {{ latestVerdict[d.id].downstream_pending ? '待重跑' : '非待重跑' }}
                  </b>
                </div>
                <div
                  v-for="c in latestVerdict[d.id].day_row_counts"
                  :key="c.biz_day"
                  class="muted small"
                >
                  {{ c.biz_day }}：{{ c.rows }} 行
                </div>
              </template>
              <span v-else class="muted">暂无装载</span>
            </td>
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
