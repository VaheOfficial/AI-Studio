import { Badge } from '@studio/ui'
import s from './ToolCallCard.module.css'

/** Structured results share the same quiet field/list treatment across tool families. */
export function ToolResult({ output, error }: { output: string; error?: boolean }) {
  let value: unknown = output
  try { value = JSON.parse(output) } catch { /* Text output remains text. */ }
  return <div className={error ? s.resultError : s.structuredResult}><Value value={value} depth={0} /></div>
}

function Value({ value, depth }: { value: unknown; depth: number }) {
  if (value == null) return <span className={s.meta}>None</span>
  if (typeof value === 'boolean') return <Badge>{value ? 'Yes' : 'No'}</Badge>
  if (typeof value !== 'object') return <span className={s.resultText}>{String(value)}</span>
  if (Array.isArray(value) && value.every(item => item == null || typeof item !== 'object')) return <span className={s.resultText}>{value.length ? value.map(item => item == null ? 'None' : String(item)).join(', ') : 'No items'}</span>
  const entries = Object.entries(value)
  if (!entries.length) return <span className={s.meta}>{Array.isArray(value) ? 'No items' : 'No additional details'}</span>
  if (depth >= 2) return <details className={s.resultDisclosure}><summary>{entries.length} {Array.isArray(value) ? 'items' : 'fields'}</summary><pre className={s.pre}>{JSON.stringify(value, null, 2)}</pre></details>
  return <dl className={s.resultFields}>{entries.slice(0, 12).map(([key, item]) => <div key={key}>
    <dt>{Array.isArray(value) ? Number(key) + 1 : key.replaceAll('_', ' ')}</dt>
    <dd><Value value={item} depth={depth + 1} /></dd>
  </div>)}{entries.length > 12 && <div><dt>More</dt><dd><details className={s.resultDisclosure}><summary>{entries.length - 12} additional entries</summary><pre className={s.pre}>{JSON.stringify(Array.isArray(value) ? value.slice(12) : Object.fromEntries(entries.slice(12)), null, 2)}</pre></details></dd></div>}</dl>
}
