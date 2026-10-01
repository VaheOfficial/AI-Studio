import { useMemo } from 'react'
import { cn } from '../../lib/cn'
import s from './DiffView.module.css'

interface Row {
  kind: 'add' | 'del' | 'ctx' | 'hunk' | 'note'
  text: string
  oldNo?: number
  newNo?: number
}

function parse(diff: string): Row[] {
  const rows: Row[] = []
  let oldNo = 0
  let newNo = 0
  for (const line of diff.split('\n')) {
    if (line.startsWith('---') || line.startsWith('+++')) continue
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/.exec(line)
    if (hunk) {
      oldNo = Number(hunk[1])
      newNo = Number(hunk[2])
      rows.push({ kind: 'hunk', text: line })
    } else if (line.startsWith('+')) rows.push({ kind: 'add', text: line.slice(1), newNo: newNo++ })
    else if (line.startsWith('-')) rows.push({ kind: 'del', text: line.slice(1), oldNo: oldNo++ })
    else if (line.startsWith(' ')) rows.push({ kind: 'ctx', text: line.slice(1), oldNo: oldNo++, newNo: newNo++ })
    else if (line.trim()) rows.push({ kind: 'note', text: line })
  }
  return rows
}

export interface DiffViewProps {
  /** Unified diff text (`diff -u` / difflib format). */
  diff: string
  /** Soft-wrap long lines (default on). */
  wrap?: boolean
  className?: string
}

/** Unified diff with old/new line numbers and added/removed highlighting. */
export function DiffView({ diff, wrap = true, className }: DiffViewProps) {
  const rows = useMemo(() => parse(diff), [diff])
  if (!rows.length) return <div className={cn(s.empty, className)}>No changes</div>
  return (
    <div className={cn(s.diff, wrap && s.wrap, className)} role="table" aria-label="File changes">
      {rows.map((r, i) => (
        <div key={i} className={cn(s.row, s[r.kind])} role="row">
          <span className={s.no}>{r.oldNo ?? ''}</span>
          <span className={s.no}>{r.newNo ?? ''}</span>
          <span className={s.sign}>{r.kind === 'add' ? '+' : r.kind === 'del' ? '−' : ''}</span>
          <span className={s.text}>{r.text || ' '}</span>
        </div>
      ))}
    </div>
  )
}
