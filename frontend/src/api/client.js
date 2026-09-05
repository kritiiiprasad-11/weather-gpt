const BASE = import.meta.env.VITE_API_BASE || '';

async function getJSON(path, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  );
  const res = await fetch(`${BASE}/api${path}?${qs}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export const api = {
  health: () => getJSON('/health'),
  geocode: (q) => getJSON('/geocode', { q }),
  current: (p) => getJSON('/weather/current', p),
  forecast: (p) => getJSON('/weather/forecast', p),
  alerts: (p) => getJSON('/alerts', p),
  advisory: (p) => getJSON('/advisory', p),
  climate: (p) => getJSON('/climate/compare', p),
};

/**
 * POST /api/chat/stream and hand back events as they arrive.
 * EventSource can't do POST, so we read the body stream directly.
 *
 * onEvent receives: {type:'tool'|'card'|'token'|'done'|'error', ...}
 */
export async function streamChat(payload, onEvent, signal) {
  const res = await fetch(`${BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`Chat failed (${res.status})`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? '';
    for (const frame of frames) {
      const line = frame.split('\n').find((l) => l.startsWith('data:'));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}

/** Live threshold checks pushed from the server for one coordinate. */
export function openAlertSocket(lat, lon, onBundle) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = BASE ? BASE.replace(/^https?:\/\//, '') : window.location.host;
  const ws = new WebSocket(`${proto}://${host}/ws/alerts`);
  ws.onopen = () => ws.send(JSON.stringify({ lat, lon }));
  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (!data.error) onBundle(data);
    } catch {
      /* ignore */
    }
  };
  return ws;
}
