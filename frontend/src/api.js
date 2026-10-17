const BASE_URL = 'http://localhost:8000'

export async function fetchState() {
  const response = await fetch(`${BASE_URL}/state`)
  return response.json()
}

export async function resetSimulator(config) {
  const response = await fetch(`${BASE_URL}/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config)
  })
  return response.json()
}

export async function putKey(key, value) {
  const response = await fetch(`${BASE_URL}/put`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, value })
  })
  return response.json()
}

export async function deleteKey(key) {
  const response = await fetch(`${BASE_URL}/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key })
  })
  return response.json()
}

export async function getKey(key) {
  const response = await fetch(`${BASE_URL}/get/${encodeURIComponent(key)}`)
  return response.json()
}

export async function scanRange(lo, hi) {
  const response = await fetch(`${BASE_URL}/scan?lo=${encodeURIComponent(lo)}&hi=${encodeURIComponent(hi)}`)
  return response.json()
}
