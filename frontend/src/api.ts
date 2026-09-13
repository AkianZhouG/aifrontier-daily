let csrfToken = ''

export async function initializeSession() {
  let response: Response
  try {
    response = await fetch('/api/session', { credentials: 'same-origin' })
  } catch {
    throw new Error('无法连接本机服务，请确认服务仍在运行')
  }
  if (!response.ok) throw new Error('无法建立本地控制会话')
  const data = await response.json()
  csrfToken = data.csrf_token
}

export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (options.body && !headers.has('content-type')) headers.set('content-type', 'application/json')
  const method = (options.method || 'GET').toUpperCase()
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    headers.set('x-frontier-csrf', csrfToken)
  }
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers,
      credentials: 'same-origin',
    })
  } catch {
    throw new Error('无法连接本机服务，请确认服务仍在运行')
  }
  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : '请求参数不符合要求'
    } catch {}
    throw new Error(detail)
  }
  return response.json()
}
