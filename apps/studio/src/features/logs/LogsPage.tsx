import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ScrollText, Search, Trash2 } from 'lucide-react'
import { Button, EmptyState, Input, SegmentedControl, cn } from '@studio/ui'
import { useLive, type LogLine } from '../../api/live'
import s from './LogsPage.module.css'

type Level = 'all' | 'warn' | 'error'

export default function LogsPage() {
  const logs = useLive((st) => st.logs)
  const clear = useLive((st) => st.clearLogs)
  const [level, setLevel] = useState<Level>('all')
  const [query, setQuery] = useState('')
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  const shown = useMemo(() => {
    const q = query.toLowerCase()
    return logs.filter(
      (l: LogLine) =>
        (level === 'all' || (level === 'warn' ? l.level === 'warn' || l.level === 'error' : l.level === 'error')) &&
        (!q || l.message.toLowerCase().includes(q) || l.source.toLowerCase().includes(q)),
    )
  }, [logs, level, query])

  useLayoutEffect(() => {
    const el = scroller.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [shown])

  return (
    <div className={s.page}>
      <div className={s.toolbar}>
        <h1 className={s.title}>
          <ScrollText size={18} /> Logs
        </h1>
        <Input iconLeft={<Search />} size="sm" placeholder="Filter…" value={query} onChange={(e) => setQuery(e.target.value)} className={s.search} />
        <SegmentedControl<Level>
          size="sm"
          value={level}
          onValueChange={setLevel}
          segments={[
            { value: 'all', label: 'All' },
            { value: 'warn', label: 'Warnings' },
            { value: 'error', label: 'Errors' },
          ]}
        />
        <div className={s.spacer} />
        <Button size="sm" variant="ghost" iconLeft={<Trash2 />} onClick={clear}>
          Clear
        </Button>
      </div>
      <div
        ref={scroller}
        className={s.console}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
        }}
      >
        {shown.length === 0 ? (
          <EmptyState icon={<ScrollText />} title="No log lines" description="Server, runtime and worker output streams here live while the app is open." />
        ) : (
          shown.map((l) => (
            <div key={l.id} className={cn(s.line, s[l.level])}>
              <span className={s.ts}>{new Date(l.ts).toLocaleTimeString()}</span>
              <span className={s.source}>{l.source}</span>
              <span className={s.msg}>{l.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
