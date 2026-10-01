import type { ReactNode } from 'react'
import { CheckCircle2, Circle, CircleDot, FileText, Folder, Globe, Hand, ListChecks, SquareTerminal } from 'lucide-react'
import { Badge, Button, DiffView, Spinner, cn } from '@studio/ui'
import type { ToolDisplay } from '../../api/contracts/workspace'
import type { ToolCall } from '../../api/types'
import { useWorkspacePanel } from './workspace/panel'
import { useChatLightbox } from './lightbox'
import { AutomationBody, CalcBody, ClockBody, ConversionBody, PythonBody, WeatherBody } from './WidgetBodies'
import s from './ToolCallCard.module.css'

/**
 * Tool renderer registry (OpenMuse `useRenderTool` per tool → one body per display kind). Each body renders the
 * typed `display` the server attaches to a call; calls without a display fall back to the generic details.
 */
type Body<K extends ToolDisplay['kind']> = (props: { call: ToolCall; display: Extract<ToolDisplay, { kind: K }> }) => ReactNode

const TerminalBody: Body<'terminal'> = ({ display }) => {
  const showTerminal = useWorkspacePanel((p) => p.showTerminal)
  return (
    <div className={s.bodyBlock}>
      <div className={s.termHead}>
        <code className={s.command}>
          <span className={s.prompt}>$</span> {display.command}
        </code>
        {display.status === 'running' && <Spinner size={12} />}
        {display.status === 'background' && <Badge tone="info" size="sm">background</Badge>}
        {display.status === 'exited' && (
          <Badge tone={display.exit_code === 0 ? 'success' : 'danger'} size="sm">
            exit {display.exit_code}
          </Badge>
        )}
      </div>
      {display.excerpt && <pre className={cn(s.pre, s.terminalPre)}>{display.excerpt}</pre>}
      <div className={s.bodyActions}>
        <Button size="sm" variant="ghost" iconLeft={<SquareTerminal />} onClick={() => showTerminal(display.terminal_id)}>
          Open in terminal
        </Button>
      </div>
    </div>
  )
}

const DiffBody: Body<'diff'> = ({ display }) => {
  const showFile = useWorkspacePanel((p) => p.showFile)
  return (
    <div className={s.bodyBlock}>
      <div className={s.fileHead}>
        <FileText size={13} />
        <button className={s.link} onClick={() => showFile(display.path)}>
          {display.path}
        </button>
        {display.created && <Badge tone="accent" size="sm">new</Badge>}
        <span className={s.added}>+{display.added}</span>
        <span className={s.removed}>−{display.removed}</span>
      </div>
      <DiffView diff={display.diff} className={s.diff} />
    </div>
  )
}

const FileBody: Body<'file'> = ({ display }) => {
  const showFile = useWorkspacePanel((p) => p.showFile)
  return (
    <div className={s.fileHead}>
      <FileText size={13} />
      <button className={s.link} onClick={() => showFile(display.path)}>
        {display.path}
      </button>
      <span className={s.meta}>
        {display.lines === display.total_lines ? `${display.total_lines} lines` : `${display.lines} of ${display.total_lines} lines`}
      </span>
    </div>
  )
}

const FilesBody: Body<'files'> = ({ display }) => {
  const showFile = useWorkspacePanel((p) => p.showFile)
  if (!display.items.length) return <p className={s.meta}>Nothing found</p>
  return (
    <ul className={s.fileList}>
      {display.items.slice(0, 40).map((it, i) => (
        <li key={`${it.path}:${it.line ?? i}`}>
          {it.dir ? <Folder size={12} /> : <FileText size={12} />}
          {it.dir ? (
            <span className={s.mono}>{it.path}/</span>
          ) : (
            <button className={s.link} onClick={() => showFile(it.path)}>
              {it.path}
              {it.line != null && `:${it.line}`}
            </button>
          )}
          {it.text && <span className={s.matchText}>{it.text.trim()}</span>}
        </li>
      ))}
      {(display.truncated || display.items.length > 40) && <li className={s.meta}>… more results</li>}
    </ul>
  )
}

const BrowserBody: Body<'browser'> = ({ display }) => {
  const { showBrowser } = useWorkspacePanel()
  let host = display.url
  try {
    host = new URL(display.url).host
  } catch {
    /* about:blank and friends */
  }
  return (
    <div className={s.bodyBlock}>
      <div className={s.fileHead}>
        <Globe size={13} />
        <span className={s.pageTitle}>{display.title || host}</span>
        <span className={s.meta}>{host}</span>
      </div>
      {display.screenshot && (
        <button className={s.shot} onClick={showBrowser} aria-label="Open the live browser">
          <img src={display.screenshot} alt={`Screenshot of ${display.title || host}`} loading="lazy" />
        </button>
      )}
      <div className={s.bodyActions}>
        <Button size="sm" variant="ghost" iconLeft={<Hand />} onClick={showBrowser}>
          Watch or take control
        </Button>
      </div>
    </div>
  )
}

export function PlanList({ items }: { items: { text: string; status: 'pending' | 'in_progress' | 'done' }[] }) {
  return (
    <ul className={s.plan}>
      {items.map((it, i) => (
        <li key={i} data-status={it.status}>
          {it.status === 'done' ? <CheckCircle2 size={14} /> : it.status === 'in_progress' ? <CircleDot size={14} /> : <Circle size={14} />}
          <span>{it.text}</span>
        </li>
      ))}
    </ul>
  )
}

const PlanBody: Body<'plan'> = ({ display }) => <PlanList items={display.items} />

const TaskBody: Body<'task'> = ({ display }) => {
  const showTasks = useWorkspacePanel((p) => p.showTasks)
  return (
    <div className={s.bodyActions}>
      <span className={s.meta}>Background task “{display.title}” runs on its own; you'll be notified when it's done.</span>
      <Button size="sm" variant="ghost" iconLeft={<ListChecks />} onClick={showTasks}>
        Show tasks
      </Button>
    </div>
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, '')
  } catch {
    return url
  }
}

/** Web results / pages read, numbered like the answer's [n] citations. */
const SourcesBody: Body<'sources'> = ({ display }) => {
  if (!display.items.length) return <p className={s.meta}>No sources</p>
  return (
    <ol className={s.sources}>
      {display.items.map((it) => (
        <li key={it.n}>
          <span className={s.sourceNum}>{it.n}</span>
          <div className={s.sourceText}>
            <a className={s.sourceTitle} href={it.url} target="_blank" rel="noreferrer">
              {it.title}
            </a>
            <span className={s.meta}>{hostOf(it.url)}</span>
            {it.snippet && <span className={s.sourceSnippet}>{it.snippet}</span>}
          </div>
        </li>
      ))}
    </ol>
  )
}

const ImageBody: Body<'image'> = ({ display }) => (
  <div className={s.bodyBlock}>
    {display.question && <span className={s.meta}>{display.question}</span>}
    <button className={cn(s.shot, s.zoom)} onClick={() => useChatLightbox.getState().show(display.url, display.question)}>
      <img src={display.url} alt={display.question ?? 'Image the agent looked at'} loading="lazy" />
    </button>
  </div>
)

/** An answered question (the open one is asked in the card's attention area — see ToolCallCard). */
const QuestionBody: Body<'question'> = ({ display }) =>
  display.answer == null ? (
    <span className={s.meta}>Waiting for your answer</span>
  ) : (
    <div className={s.bodyBlock}>
      <span className={s.questionText}>{display.question}</span>
      <span className={s.meta}>
        You answered: <strong>{display.answer}</strong>
      </span>
    </div>
  )

const BODIES: { [K in ToolDisplay['kind']]: Body<K> } = {
  terminal: TerminalBody,
  diff: DiffBody,
  file: FileBody,
  files: FilesBody,
  browser: BrowserBody,
  plan: PlanBody,
  task: TaskBody,
  sources: SourcesBody,
  image: ImageBody,
  question: QuestionBody,
  python: PythonBody,
  weather: WeatherBody,
  calc: CalcBody,
  conversion: ConversionBody,
  clock: ClockBody,
  automation: AutomationBody,
}

export function ToolBody({ call }: { call: ToolCall }) {
  const display = call.display
  if (!display) return null
  const Render = BODIES[display.kind] as Body<typeof display.kind>
  return <Render call={call} display={display} />
}

/** What an approval is about, rendered from the arguments before the tool runs. */
export function ApprovalPreview({ call }: { call: ToolCall }) {
  const a = call.args as Record<string, string | undefined>
  if (call.name === 'edit_file' && a.old_string != null && a.new_string != null) {
    const lines = (t: string, sign: string) => t.split('\n').map((l) => sign + l)
    const diff = ['@@ -1 +1 @@', ...lines(a.old_string, '-'), ...lines(a.new_string, '+')].join('\n')
    return (
      <div className={s.bodyBlock}>
        <div className={s.fileHead}>
          <FileText size={13} />
          <span className={s.mono}>{a.path}</span>
        </div>
        <DiffView diff={diff} className={s.diff} />
      </div>
    )
  }
  if (call.name === 'write_file' && a.content != null) {
    return (
      <div className={s.bodyBlock}>
        <div className={s.fileHead}>
          <FileText size={13} />
          <span className={s.mono}>{a.path}</span>
          <span className={s.meta}>{a.content.split('\n').length} lines</span>
        </div>
        <pre className={s.pre}>{a.content.split('\n').slice(0, 40).join('\n')}</pre>
      </div>
    )
  }
  return null
}
