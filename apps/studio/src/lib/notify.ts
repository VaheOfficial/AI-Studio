/**
 * Telling the user about something that happened while they were looking elsewhere: a question from the agent, an
 * approval it waits for, a long reply that finished, an automation's report.
 *
 * When the app's window is not in front this is a system notification. In the desktop app the shell shows it, flashes
 * the taskbar button, and a click brings the window forward on the chat it is about. In a browser it is the page's own
 * notification, when the user allowed those.
 */
export interface Note {
  title: string
  body?: string
  /** A newer note with the same tag replaces the older one. */
  tag?: string
  /** Where a click leads, as an in-app path ("/chat/<id>"). */
  path?: string
}

interface Shell {
  notify?: (note: Note) => void
  onOpen?: (handler: (path: string) => void) => void
}

const shell = (window as { desktop?: Shell }).desktop

/** The user is not looking at the app: its window is hidden, minimized or behind another one. */
export const away = () => document.hidden || !document.hasFocus()

let open: (path: string) => void = (path) => window.location.assign(path)

/** How a clicked notification opens its chat: the app's own navigation, set once the router is up. */
export function onNotificationOpen(navigate: (path: string) => void) {
  open = navigate
}

shell?.onOpen?.((path) => open(path))

const short = (text: string | undefined, max: number) => (text && text.length > max ? `${text.slice(0, max - 1)}…` : text)

/** Shows a system notification; false when there is no way to (a browser that was not allowed to). */
export function notifySystem(note: Note): boolean {
  const body = short(note.body?.trim(), 220)
  if (shell?.notify) {
    shell.notify({ ...note, body })
    return true
  }
  if (!('Notification' in window) || Notification.permission !== 'granted') return false
  const n = new Notification(note.title, { body, tag: note.tag })
  n.onclick = () => {
    window.focus()
    if (note.path) open(note.path)
  }
  return true
}
