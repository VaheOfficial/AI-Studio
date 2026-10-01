import { useEffect, useState, useSyncExternalStore } from 'react'
import { ArrowLeft, ArrowRight, Globe, Hand, RotateCw, Terminal as ConsoleIcon } from 'lucide-react'
import { Badge, BrowserView, Button, IconButton, Input, cn } from '@studio/ui'
import { useLive } from '../../../api/live'
import { browserFrames, browserLive, useBrowser, useHistory, useNavigate, useTakeover } from '../../../api/workspace'
import s from './BrowserTab.module.css'

/** Live view of the agent's browser with an address bar, takeover and the page console. */
export function BrowserTab({ sessionId }: { sessionId: string }) {
  const { data } = useBrowser(sessionId)
  const state = data?.state
  const navigate = useNavigate(sessionId)
  const history = useHistory(sessionId)
  const takeover = useTakeover(sessionId)
  const connected = useLive((st) => st.status === 'open')
  const frame = useSyncExternalStore(
    (fn) => browserFrames.subscribe(sessionId, fn),
    () => browserFrames.get(sessionId),
  )
  // What the user is typing; otherwise the bar follows the page
  const [typed, setTyped] = useState<string>()
  const address = typed ?? state?.url ?? ''
  const [consoleOpen, setConsoleOpen] = useState(false)

  // Stream frames while this tab is visible (re-sent after reconnects and when the page opens)
  useEffect(() => {
    if (!connected || !state?.open) return
    browserLive.watch(sessionId, true)
    return () => void browserLive.watch(sessionId, false)
  }, [sessionId, connected, state?.open])

  const errors = data?.console.filter((c) => c.level === 'error').length ?? 0
  const controlling = !!state?.takeover

  return (
    <div className={s.tab}>
      <form
        className={s.bar}
        onSubmit={(e) => {
          e.preventDefault()
          if (address.trim()) navigate.mutate({ url: address.trim() }, { onSettled: () => setTyped(undefined) })
        }}
      >
        <IconButton label="Back" icon={<ArrowLeft />} size="sm" disabled={!state?.open} onClick={() => history.mutate({ action: 'back' })} />
        <IconButton label="Forward" icon={<ArrowRight />} size="sm" disabled={!state?.open} onClick={() => history.mutate({ action: 'forward' })} />
        <IconButton label="Reload" icon={<RotateCw />} size="sm" disabled={!state?.open} onClick={() => history.mutate({ action: 'reload' })} />
        <Input
          size="sm"
          className={s.address}
          iconLeft={<Globe size={13} />}
          value={address}
          placeholder="Enter an address, e.g. example.com"
          onChange={(e) => setTyped(e.target.value)}
          spellCheck={false}
        />
        <Button
          size="sm"
          variant={controlling ? 'primary' : 'secondary'}
          iconLeft={<Hand />}
          disabled={!state?.open}
          loading={takeover.isPending}
          onClick={() => takeover.mutate({ on: !controlling })}
        >
          {controlling ? 'Hand back' : 'Take control'}
        </Button>
      </form>
      {controlling && <p className={s.notice}>You're in control — the agent's browser tools wait until you hand it back.</p>}
      <div className={s.view}>
        <BrowserView
          frame={state?.open ? frame : undefined}
          interactive={controlling}
          onInput={(input) => browserLive.input(sessionId, input)}
          placeholder={
            navigate.isPending ? (
              'Opening…'
            ) : (
              <span>
                The agent's browser opens here when it browses — or enter an address above.
                <br />
                You can watch it live and take control at any time.
              </span>
            )
          }
        />
      </div>
      <div className={cn(s.console, consoleOpen && s.consoleOpen)}>
        <button className={s.consoleHead} onClick={() => setConsoleOpen(!consoleOpen)} aria-expanded={consoleOpen}>
          <ConsoleIcon size={12} />
          Console
          {errors > 0 && <Badge tone="danger" size="sm">{errors}</Badge>}
          <span className={s.title}>{state?.title}</span>
        </button>
        {consoleOpen && (
          <div className={s.logs}>
            {data?.console.length ? (
              data.console.map((c, i) => (
                <div key={i} className={s.log} data-level={c.level}>
                  {c.text}
                </div>
              ))
            ) : (
              <p className={s.empty}>No console messages</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
