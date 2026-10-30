/** Client bridge for a document editor or add-in. Only supplied handlers are advertised. */
export interface DocumentCommand {
  description: string
  parameters: Record<string, unknown>
  execute: (args: Record<string, unknown>) => unknown | Promise<unknown>
}
export function connectDocument(options: { url: string; token: string; sessionId: string; title: string; kind: string; commands: Record<string, DocumentCommand>; onState?: (state: 'connected' | 'closed' | 'error') => void }) {
  const socket = new WebSocket(options.url)
  socket.onopen = () => socket.send(JSON.stringify({ token: options.token, session_id: options.sessionId, title: options.title, kind: options.kind,
    tools: Object.entries(options.commands).map(([name, command]) => ({ name, description: command.description, parameters: command.parameters })) }))
  socket.onmessage = async event => {
    const message = JSON.parse(event.data as string) as { type: string; id: string; name: string; args: Record<string, unknown> }
    if (message.type === 'connected') { options.onState?.('connected'); return }
    if (message.type !== 'command') return
    try {
      const handler = options.commands[message.name]
      if (!handler) throw new Error('Unsupported document command')
      const result = await handler.execute(message.args)
      socket.send(JSON.stringify({ type: 'result', id: message.id, ok: true, result }))
    } catch (e) {
      socket.send(JSON.stringify({ type: 'result', id: message.id, ok: false, error: (e as Error).message }))
    }
  }
  socket.onclose = () => options.onState?.('closed')
  socket.onerror = () => options.onState?.('error')
  return () => socket.close()
}
