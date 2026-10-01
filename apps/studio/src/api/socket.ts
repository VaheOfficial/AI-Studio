import type { ClientMessage, ServerEvent } from './types'

export type SocketStatus = 'connecting' | 'open' | 'closed'

type EventListener = (event: ServerEvent) => void
type StatusListener = (status: SocketStatus) => void

/**
 * The app's single realtime connection (`/api/ws`). Reconnects with capped backoff; the server
 * re-sends a full snapshot in `hello` on every connect, so nothing is lost while disconnected.
 */
class StudioSocket {
  private ws: WebSocket | null = null
  private events = new Set<EventListener>()
  private statuses = new Set<StatusListener>()
  private backoff = 500
  private retry: ReturnType<typeof setTimeout> | undefined
  private users = 0
  status: SocketStatus = 'closed'

  /** Reference-counted: the socket stays open while at least one caller holds it. */
  acquire(): () => void {
    if (this.users++ === 0) this.connect()
    return () => {
      if (--this.users === 0) this.disconnect()
    }
  }

  onEvent(fn: EventListener) {
    this.events.add(fn)
    return () => void this.events.delete(fn)
  }

  onStatus(fn: StatusListener) {
    this.statuses.add(fn)
    return () => void this.statuses.delete(fn)
  }

  /** Returns false when not connected — callers surface that instead of queueing blindly. */
  send(message: ClientMessage): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false
    this.ws.send(JSON.stringify(message))
    return true
  }

  private setStatus(status: SocketStatus) {
    this.status = status
    this.statuses.forEach((fn) => fn(status))
  }

  private connect() {
    clearTimeout(this.retry)
    const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`
    const ws = new WebSocket(url)
    this.ws = ws
    this.setStatus('connecting')

    ws.onopen = () => {
      this.backoff = 500
      this.setStatus('open')
    }
    ws.onmessage = (m) => {
      let event: ServerEvent
      try {
        event = JSON.parse(m.data as string) as ServerEvent
      } catch {
        console.error('Unparseable server frame', m.data)
        return
      }
      this.events.forEach((fn) => fn(event))
    }
    ws.onclose = () => {
      if (this.ws !== ws) return // superseded by a newer connection
      this.ws = null
      this.setStatus('closed')
      if (this.users > 0) {
        this.retry = setTimeout(() => this.connect(), this.backoff)
        this.backoff = Math.min(this.backoff * 2, 8000)
      }
    }
  }

  private disconnect() {
    clearTimeout(this.retry)
    const ws = this.ws
    this.ws = null
    ws?.close()
    this.setStatus('closed')
  }
}

export const socket = new StudioSocket()
