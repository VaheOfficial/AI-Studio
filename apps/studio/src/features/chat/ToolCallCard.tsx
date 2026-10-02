import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Ban, Check, ChevronRight, MessageCircleQuestion, ShieldAlert, X } from 'lucide-react'
import { Button, Input, Spinner, cn } from '@studio/ui'
import type { ToolCall } from '../../api/types'
import { OutputView } from '../../components/OutputView'
import type { ToolDisplay } from '../../api/contracts/workspace'
import { useChatPrefs } from './prefs'
import { useChatLightbox } from './lightbox'
import { ApprovalPreview, ToolBody } from './ToolBodies'
import { toolMeta } from './toolMeta'
import s from './ToolCallCard.module.css'

/** Displays that are the point of the call — shown open by default. */
// Widgets and results the user asked for show inline; the rest stays one line until opened
const OPEN_BY_DEFAULT = new Set<ToolDisplay['kind']>([
  'terminal', 'diff', 'browser', 'plan', 'task', 'image', 'question',
  'python', 'weather', 'calc', 'conversion', 'clock', 'automation',
])

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
  const meta = toolMeta(call.name)
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
              ) : typeof call.args.check === 'string' ? (
                <>
                  The agent wants to run this check by itself every {Number(call.args.check_minutes) || 15} minutes, without asking each
                  time. Allow it?
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
