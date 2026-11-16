export function nativeDispatch(event) {
  const card = event.input?.description;
  const match = /^\[([^\]]+)\] ([^|]+) \| (.+)$/.exec(card || '');
  const role = event.input?.agentID || event.input?.agent || event.input?.agentId;
  const callID = event.callID || event.id || event.toolCallID;
  if (!match || !role || !callID) {
    throw new Error('Native subagent requires node card, role, and call ID');
  }
  return { nodeID: match[1], capability: match[2].trim(), writeScope: match[3].trim(),
    role, callID, card };
}

export function childSession(result) {
  const direct = result?.sessionID || result?.sessionId || result?.metadata?.sessionID;
  if (typeof direct === 'string' && direct) return direct;
  const content = result?.content;
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content);
      return parsed.sessionID || parsed.sessionId || null;
    } catch { /* Host result is free text. */ }
  }
  return null;
}

export function nativeToolStatus(event) {
  if (event.status === 'completed') return 'completed';
  if (event.error?.name === 'AbortError') return 'cancelled';
  return 'error';
}
