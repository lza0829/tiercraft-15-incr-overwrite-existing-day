export async function getJson(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

async function sendJson(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function postJson(url, body) {
  return sendJson('POST', url, body)
}

export async function putJson(url, body) {
  return sendJson('PUT', url, body)
}

export function modeLabel(mode) {
  return mode === 'full' ? '全量' : '增量'
}
