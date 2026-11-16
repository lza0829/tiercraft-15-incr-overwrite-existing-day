<script setup>
import { computed, ref } from 'vue'
import { putJson, postJson } from '../api'

const props = defineProps({
  domains: { type: Array, default: () => [] },
  domainId: { type: Number, default: 1 },
})
const emit = defineEmits(['loaded', 'mode-changed', 'error'])

const busy = ref(false)
const err = ref('')
const result = ref(null)

const domain = computed(() => props.domains.find((d) => d.id === props.domainId) || null)
const mode = computed(() => (domain.value ? domain.value.load_mode : 'incremental'))
const pending = computed(() => domain.value && domain.value.downstream_status === '待重跑')

async function changeMode(event) {
  const next = event.target.value
  busy.value = true
  err.value = ''
  try {
    const updated = await putJson(`/api/domains/${props.domainId}/load-mode`, { load_mode: next })
    emit('mode-changed', updated)
  } catch (e) {
    err.value = String(e.message || e)
    emit('error', err.value)
  } finally {
    busy.value = false
  }
}

async function load() {
  busy.value = true
  err.value = ''
  result.value = null
  try {
    const job = await postJson('/api/layers/paste/load', { domain_id: props.domainId })
    result.value = job
    emit('loaded', job)
  } catch (e) {
    err.value = String(e.message || e)
    emit('error', err.value)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <div class="load-panel">
    <div class="toolbar">
      <label>
        装载模式
        <select :value="mode" :disabled="busy" @change="changeMode">
          <option value="incremental">增量（只追加新业务日）</option>
          <option value="full">全量（清空贴源后重载）</option>
        </select>
      </label>
      <span class="mode-badge" :class="mode === 'full' ? 'badge-full' : 'badge-incr'">
        {{ mode === 'full' ? '全量' : '增量' }}
      </span>
      <button :disabled="busy" @click="load">
        {{ busy ? '装载中…' : mode === 'full' ? '执行全量重载' : '执行增量装载' }}
      </button>
      <span v-if="result" :class="result.status === '成功' ? 'ok' : 'warn'">
        最近装载：{{ result.status }}
      </span>
    </div>

    <p v-if="mode === 'full'" class="hint warn">
      全量会清空该主题域贴源后按夹具重载，并清空明细/汇总，置为待重跑。
    </p>
    <p v-else class="hint">
      增量只写入贴源中尚不存在的业务日；已存在的业务日整日跳过，不覆盖、不删除已有行。
    </p>

    <p v-if="err" class="err">{{ err }}</p>

    <div v-if="result" class="panel result-panel">
      <h3>
        装载报告 <span :class="result.status === '成功' ? 'ok' : 'warn'">· {{ result.status }}</span>
        <span class="muted small"> 编号 {{ result.id }} · {{ result.mode_label }} · {{ result.created_at }}</span>
      </h3>
      <table>
        <tbody>
          <tr><th>模式</th><td>{{ result.mode_label }}</td></tr>
          <tr>
            <th>写入业务日</th>
            <td>
              <span v-if="result.written_days.length">{{ result.written_days.join('、') }}</span>
              <span v-else class="muted">无</span>
              <span class="muted small">（{{ result.out_count }} 行）</span>
            </td>
          </tr>
          <tr>
            <th>跳过业务日</th>
            <td>
              <span v-if="result.skipped_days.length" class="warn">{{ result.skipped_days.join('、') }}</span>
              <span v-else class="muted">无</span>
            </td>
          </tr>
          <tr v-if="result.fail_reason"><th>失败原因</th><td class="warn">{{ result.fail_reason }}</td></tr>
        </tbody>
      </table>
      <p v-if="result.status === '成功' && result.mode === 'full'" class="warn">
        全量装载完成：明细层与汇总层已清空，需重跑「贴源到明细」「明细到汇总」后才能恢复对齐展示。
      </p>
      <p v-else-if="result.status === '成功' && result.written_days.length" class="hint">
        新增业务日尚未进入下游，明细/汇总保持原样并标记为待重跑。
      </p>
    </div>
    <p v-else-if="pending" class="hint warn">
      当前主题域下游处于「待重跑」：明细/汇总与贴源尚未对齐，请重跑下游任务。
    </p>
  </div>
</template>
