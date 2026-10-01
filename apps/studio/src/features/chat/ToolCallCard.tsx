import { useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import {
  AlarmClock,
  ArrowLeftRight,
  AudioLines,
  Ban,
  BookOpen,
  Boxes,
  Brain,
  Calculator,
  Camera,
  Check,
  ChevronRight,
  Clapperboard,
  Clock,
  CloudSun,
  Cpu,
  Download,
  Eye,
  FilePen,
  FileSearch,
  FileText,
  FolderTree,
  Globe,
  ImagePlus,
  Images,
  Keyboard,
  Languages,
  ListChecks,
  ListTodo,
  MessageCircleQuestion,
  Mic2,
  MousePointerClick,
  Music,
  Newspaper,
  PenLine,
  Play,
  Plug,
  Power,
  RotateCcw,
  ScanText,
  Search,
  ShieldAlert,
  Split,
  Square,
  SquareCode,
  Telescope,
  Terminal,
  Trash2,
  UserRoundPlus,
  Wand2,
  Wrench,
  X,
} from 'lucide-react'
import { Button, Input, Spinner, cn } from '@studio/ui'
import type { ToolCall } from '../../api/types'
import { OutputView } from '../../components/OutputView'
import type { ToolDisplay } from '../../api/contracts/workspace'
import { useChatPrefs } from './prefs'
import { useChatLightbox } from './lightbox'
import { ApprovalPreview, ToolBody } from './ToolBodies'
import s from './ToolCallCard.module.css'

/** Displays that are the point of the call — shown open by default. */
// Widgets and results the user asked for show inline; the rest stays one line until opened
const OPEN_BY_DEFAULT = new Set<ToolDisplay['kind']>([
  'terminal', 'diff', 'browser', 'plan', 'task', 'image', 'question',
  'python', 'weather', 'calc', 'conversion', 'clock', 'automation',
])

const TOOL_META: Record<string, { icon: ReactNode; verb: string; primary?: string; mono?: boolean }> = {
  system_info: { icon: <Cpu />, verb: 'Checked system' },
  list_models: { icon: <Boxes />, verb: 'Listed models', primary: 'kind' },
  search_catalog: { icon: <Search />, verb: 'Searched catalog', primary: 'query' },
  install_model: { icon: <Download />, verb: 'Install model', primary: 'catalog_id' },
  delete_model: { icon: <Trash2 />, verb: 'Delete model', primary: 'model_id' },
  load_model: { icon: <Power />, verb: 'Load model', primary: 'model_id' },
  unload_model: { icon: <Power />, verb: 'Unload model', primary: 'model_id' },
  generate_image: { icon: <ImagePlus />, verb: 'Generate image', primary: 'prompt' },
  text_to_speech: { icon: <Mic2 />, verb: 'Speak', primary: 'text' },
  generate_music: { icon: <Music />, verb: 'Compose music', primary: 'tags' },
  list_dir: { icon: <FolderTree />, verb: 'List files', primary: 'path', mono: true },
  read_file: { icon: <FileText />, verb: 'Read', primary: 'path', mono: true },
  write_file: { icon: <PenLine />, verb: 'Write', primary: 'path', mono: true },
  edit_file: { icon: <FilePen />, verb: 'Edit', primary: 'path', mono: true },
  find_files: { icon: <FileSearch />, verb: 'Find files', primary: 'pattern', mono: true },
  search_files: { icon: <Search />, verb: 'Search', primary: 'pattern', mono: true },
  run_command: { icon: <Terminal />, verb: 'Run', primary: 'command', mono: true },
  start_process: { icon: <Play />, verb: 'Start process', primary: 'command', mono: true },
  read_process_output: { icon: <Terminal />, verb: 'Process output', primary: 'process_id', mono: true },
  stop_process: { icon: <Square />, verb: 'Stop process', primary: 'process_id', mono: true },
  browser_navigate: { icon: <Globe />, verb: 'Open', primary: 'url' },
  browser_click: { icon: <MousePointerClick />, verb: 'Click', primary: 'text' },
  browser_type: { icon: <Keyboard />, verb: 'Type', primary: 'text' },
  browser_read: { icon: <ScanText />, verb: 'Read page', primary: 'mode' },
  browser_screenshot: { icon: <Camera />, verb: 'Screenshot' },
  update_plan: { icon: <ListTodo />, verb: 'Plan' },
  memory: { icon: <Brain />, verb: 'Memory', primary: 'action' },
  start_task: { icon: <ListChecks />, verb: 'Background task', primary: 'title' },
  view_image: { icon: <Eye />, verb: 'Looked at', primary: 'source' },
  edit_image: { icon: <Wand2 />, verb: 'Edit image', primary: 'prompt' },
  transcribe: { icon: <AudioLines />, verb: 'Transcribe', primary: 'source' },
  list_voices: { icon: <Mic2 />, verb: 'Listed voices', primary: 'query' },
  clone_voice: { icon: <UserRoundPlus />, verb: 'Clone voice', primary: 'name' },
  separate_audio: { icon: <Split />, verb: 'Separate audio', primary: 'source' },
  start_dub: { icon: <Languages />, verb: 'Start dub', primary: 'source' },
  list_outputs: { icon: <Images />, verb: 'Searched gallery', primary: 'query' },
  ask_user: { icon: <MessageCircleQuestion />, verb: 'Asked you', primary: 'question' },
  web_search: { icon: <Search />, verb: 'Searched the web', primary: 'query' },
  fetch_url: { icon: <Newspaper />, verb: 'Read', primary: 'url' },
  research: { icon: <Telescope />, verb: 'Researched', primary: 'question' },
  generate_video: { icon: <Clapperboard />, verb: 'Make video', primary: 'prompt' },
  run_python: { icon: <SquareCode />, verb: 'Ran Python' },
  reset_python: { icon: <RotateCcw />, verb: 'Restarted Python' },
  read_skill: { icon: <BookOpen />, verb: 'Read guide', primary: 'name' },
  get_weather: { icon: <CloudSun />, verb: 'Weather', primary: 'location' },
  calculate: { icon: <Calculator />, verb: 'Calculated', primary: 'expression', mono: true },
  convert: { icon: <ArrowLeftRight />, verb: 'Converted', primary: 'from_unit' },
  world_time: { icon: <Clock />, verb: 'World time' },
  automation_create: { icon: <AlarmClock />, verb: 'Created automation', primary: 'title' },
  automation_update: { icon: <AlarmClock />, verb: 'Updated automation', primary: 'id' },
  automation_list: { icon: <AlarmClock />, verb: 'Listed automations' },
  automation_delete: { icon: <AlarmClock />, verb: 'Delete automation', primary: 'id' },
  remember: { icon: <Brain />, verb: 'Remembered', primary: 'fact' },
  forget: { icon: <Brain />, verb: 'Forgot', primary: 'id' },
}

/** A connector's tool (`<app>__<tool>`): "github · search issues". */
function connectorMeta(name: string) {
  const [app, tool] = name.split('__')
  return tool ? { icon: <Plug />, verb: `${app} · ${tool.replaceAll('_', ' ')}` } : undefined
}

function primaryText(call: ToolCall, key: string | undefined): string | undefined {
  if (call.name === 'browser_click') {
    const a = call.args
    const target = a.text ?? a.ref ?? a.selector ?? (a.x != null ? `${String(a.x)}, ${String(a.y)}` : undefined)
    return target == null ? undefined : String(target)
  }
  if (call.name === 'update_plan' && call.display?.kind === 'plan') {
    const items = call.display.items
    return `${items.filter((i) => i.status === 'done').length}/${items.length} done`
  }
  const v = key ? call.args[key] : undefined
  return v == null ? undefined : String(v)
}

export interface ToolCallCardProps {
  call: ToolCall
  onApprove: (id: string, ok: boolean) => void
  /** Answers an `ask_user` question (absent where nobody can answer, e.g. a saved message). */
  onAnswer?: (id: string, answer: string) => void
}

export function ToolCallCard({ call, onApprove, onAnswer }: ToolCallCardProps) {
  const meta = TOOL_META[call.name] ?? connectorMeta(call.name) ?? { icon: <Wrench />, verb: call.name }
  const primary = primaryText(call, meta.primary)
  const needsApproval = call.status === 'pending_approval'
  const asking = call.status === 'awaiting_input' && call.display?.kind === 'question' ? call.display : undefined
  const rich = !!call.display
  const verbose = useChatPrefs((st) => st.verbose)
  const [open, setOpen] = useState<boolean | undefined>(undefined)
  const [details, setDetails] = useState(false)
  // Verbose opens every card; otherwise rich bodies of the important kinds start open. The user's toggle wins.
  const expanded = open ?? (verbose || (!!call.display && OPEN_BY_DEFAULT.has(call.display.kind)))

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(s.card, s[call.status], (needsApproval || asking) && s.attention)}
    >
      <button className={s.head} onClick={() => setOpen(!expanded)} aria-expanded={expanded}>
        <span className={s.icon}>{meta.icon}</span>
        <span className={s.verb}>{meta.verb}</span>
        {primary != null && <span className={cn(s.primary, meta.mono && s.mono)}>{primary}</span>}
        <span className={s.state}>
          {call.status === 'running' && <Spinner size={13} />}
          {call.status === 'done' && <Check size={14} className={s.ok} />}
          {call.status === 'error' && <X size={14} className={s.err} />}
          {call.status === 'denied' && <Ban size={13} className={s.err} />}
          {needsApproval && <ShieldAlert size={14} className={s.warn} />}
          {asking && <MessageCircleQuestion size={14} className={s.warn} />}
        </span>
        <ChevronRight size={14} className={cn(s.chev, expanded && s.chevOpen)} />
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            className={s.details}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className={s.detailsInner}>
              {rich ? <ToolBody call={call} /> : <ReadableCall call={call} />}
              {rich && call.status === 'error' && call.output && <pre className={cn(s.pre, s.errorPre)}>{call.output}</pre>}
              <button className={s.moreToggle} onClick={() => setDetails(!details)}>
                {details ? 'Hide raw details' : 'Raw details'}
              </button>
              {details && (
                <>
                  <div className={s.label}>Arguments</div>
                  <pre className={s.pre}>{JSON.stringify(call.args, null, 2)}</pre>
                  {call.output && (
                    <>
                      <div className={s.label}>Result</div>
                      <pre className={s.pre}>{call.output}</pre>
                    </>
                  )}
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {needsApproval && (
        <div className={s.approval}>
          <ApprovalPreview call={call} />
          <div className={s.approvalRow}>
            <p>
              {call.name === 'run_command' || call.name === 'start_process' ? (
                <>
                  The agent wants to run <code>{String(call.args.command)}</code>
                </>
              ) : (
                <>
                  The agent wants to {meta.verb.toLowerCase()}
                  {primary ? <> <code>{primary}</code></> : null}. Allow it?
                </>
              )}
            </p>
            <div className={s.approvalActions}>
              <Button size="sm" variant="ghost" onClick={() => onApprove(call.id, false)}>
                Deny
              </Button>
              <Button size="sm" variant="primary" onClick={() => onApprove(call.id, true)}>
                Allow
              </Button>
            </div>
          </div>
        </div>
      )}

      {asking && onAnswer && <QuestionPrompt question={asking.question} options={asking.options} onAnswer={(a) => onAnswer(call.id, a)} />}

      {call.artifacts && call.artifacts.length > 0 && (
        <div className={s.artifacts}>
          {call.artifacts.map((o) => (
            <OutputView key={o.id} output={o} compact onOpen={(x) => useChatLightbox.getState().show(x.url, x.prompt)} />
          ))}
        </div>
      )}
    </motion.div>
  )
}

/** The agent's question, waiting: pick an option or answer in your own words. */
function QuestionPrompt({ question, options, onAnswer }: { question: string; options: string[]; onAnswer: (a: string) => void }) {
  const [own, setOwn] = useState('')
  const submit = () => own.trim() && onAnswer(own.trim())
  return (
    <div className={s.question}>
      <span className={s.questionText}>{question}</span>
      {options.length > 0 && (
        <div className={s.questionOptions}>
          {options.map((o) => (
            <Button key={o} size="sm" variant="secondary" onClick={() => onAnswer(o)}>
              {o}
            </Button>
          ))}
        </div>
      )}
      <div className={s.questionOwn}>
        <Input
          size="sm"
          value={own}
          placeholder={options.length ? 'Or answer in your own words…' : 'Your answer…'}
          onChange={(e) => setOwn(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) submit()
          }}
          autoFocus
        />
        <Button size="sm" variant="primary" disabled={!own.trim()} onClick={submit}>
          Answer
        </Button>
      </div>
    </div>
  )
}

/** A call without a rich display, readable: each argument as a labelled value, then the result as text. */
function ReadableCall({ call }: { call: ToolCall }) {
  const args = Object.entries(call.args)
  return (
    <>
      {args.length > 0 && (
        <dl className={s.args}>
          {args.map(([key, value]) => (
            <div key={key} className={s.arg}>
              <dt>{key.replace(/_/g, ' ')}</dt>
              <dd className={cn(typeof value !== 'string' && s.mono)}>
                {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {call.output && (
        <>
          <div className={s.label}>Result</div>
          <div className={cn(s.result, /^[[{]/.test(call.output.trimStart()) && s.mono, call.status === 'error' && s.resultError)}>
            {call.output}
          </div>
        </>
      )}
    </>
  )
}
