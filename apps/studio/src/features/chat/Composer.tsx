import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent } from 'react'
import { Link } from 'react-router'
import { ArrowUp, Bot, Cloud, CornerDownRight, Eye, EyeOff, HardDrive, ImagePlus, ListPlus, MessageCircle, Paperclip, Square, X } from 'lucide-react'
import { Button, IconButton, SegmentedControl, Select, Spinner, Textarea, cn, type SelectGroup } from '@studio/ui'
import type { AgentMode, ChatModelOption, ContextUsage } from '../../api/types'
import { formatBytes } from '../../lib/format'
import { formatUsd } from '../../lib/money'
import { COMMANDS, matchCommands, parseCommand } from './commands'
import { ContextGauge } from './ContextGauge'
import type { QueuedMessage } from './conversationQueue'
import { useChatPrefs } from './prefs'
import s from './Composer.module.css'

const isImage = (f: File) => f.type.startsWith('image/')
const COMMAND_NAMES = new Set(COMMANDS.map((c) => c.name))

// Thumbnail URLs, one per picture while it sits in the composer; released when it is removed or sent
const previews = new WeakMap<File, string>()
function previewUrl(file: File): string {
  let url = previews.get(file)
  if (!url) {
    url = URL.createObjectURL(file)
    previews.set(file, url)
  }
  return url
}
function releasePreviews(files: File[]) {
  for (const f of files) {
    const url = previews.get(f)
    if (url) URL.revokeObjectURL(url)
    previews.delete(f)
  }
}

export interface ComposerProps {
  models: ChatModelOption[]
  model: string | undefined
  onModelChange: (id: string) => void
  mode: AgentMode
  onModeChange: (m: AgentMode) => void
  streaming: boolean
  /** While a reply streams, a sent message is queued as a follow-up. */
  onSend: (text: string, files: File[]) => void | Promise<void>
  onStop: () => void
  queued: QueuedMessage[]
  queuePaused: boolean
  onRemoveQueued: (id: string) => void
  onResumeQueue: () => void
  /** Text put into the box from outside (e.g. the message a rewind removed); a new object replaces the text. */
  draft?: { text: string }
  /** How full the model's context was on the last request, and what was trimmed to fit. */
  context?: ContextUsage
  contextNote?: string
  /** Runs a slash command (`/compact`, …); resolves false when the text was not a known command. */
  onCommand: (name: string, args: string) => boolean | Promise<boolean>
  /** Something long is running for this chat (e.g. compacting): shown above the box; sending waits for it. */
  busy?: string
}

const PROVIDER_LABEL = {
  lmstudio: 'Local · LM Studio',
  llamacpp: 'Local · llama.cpp',
  ollama: 'Local · Ollama',
  openai: 'OpenAI-compatible',
  openrouter: 'OpenRouter',
}
const LOCAL_PROVIDERS = new Set(['lmstudio', 'llamacpp', 'ollama'])

/** Picker hint: per-token price for cloud models, and a warning when the model can't call tools. */
function modelHint(m: ChatModelOption): string | undefined {
  const parts: string[] = []
  if (m.price) parts.push(m.price.input || m.price.output ? `${formatUsd(m.price.input)} in · ${formatUsd(m.price.output)} out /M tok` : 'Free')
  if (!m.tools) parts.push('No tool calling')
  return parts.join(' · ') || undefined
}

export function Composer({
  models,
  model,
  onModelChange,
  mode,
  onModeChange,
  streaming,
  onSend,
  onStop,
  queued,
  queuePaused,
  onRemoveQueued,
  onResumeQueue,
  draft,
  context,
  contextNote,
  onCommand,
  busy,
}: ComposerProps) {
  const verbose = useChatPrefs((st) => st.verbose)
  const setVerbose = useChatPrefs((st) => st.setVerbose)
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const ref = useRef<HTMLTextAreaElement>(null)
  // A new draft object replaces the text (adjusted during render; the effect only moves focus)
  const [shownDraft, setShownDraft] = useState(draft)
  if (draft !== shownDraft) {
    setShownDraft(draft)
    if (draft) setText(draft.text)
  }
  useEffect(() => {
    if (draft) ref.current?.focus()
  }, [draft])
  const picker = useRef<HTMLInputElement>(null)
  const current = models.find((m) => m.id === model)
  const noTools = mode === 'agent' && current && !current.tools
  const pictures = files.filter(isImage)
  const blind = pictures.length > 0 && current && !current.vision
  // Pictures can go with any message; other files are copied into the agent's workspace folder
  const addFiles = (list: File[]) => {
    const ok = mode === 'agent' ? list : list.filter(isImage)
    if (ok.length) setFiles((prev) => [...prev, ...ok])
  }
  const onPaste = (e: ClipboardEvent) => {
    const pasted = Array.from(e.clipboardData.files)
    if (pasted.length) {
      e.preventDefault()
      addFiles(pasted)
    }
  }
  const [dragging, setDragging] = useState(false)
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    addFiles(Array.from(e.dataTransfer.files))
  }

  const groups: SelectGroup[] = (['lmstudio', 'llamacpp', 'ollama', 'openai', 'openrouter'] as const)
    .map((p) => ({
      label: PROVIDER_LABEL[p],
      options: models
        .filter((m) => m.provider === p)
        .map((m) => ({
          value: m.id,
          label: m.name,
          disabled: !m.available,
          icon: LOCAL_PROVIDERS.has(p) ? <HardDrive /> : <Cloud />,
          description: modelHint(m),
        })),
    }))
    .filter((g) => g.options.length)

  const suggestions = matchCommands(text)
  const [pick, setPick] = useState(0)
  const [shownText, setShownText] = useState(text)
  if (text !== shownText) {
    setShownText(text)
    setPick(0)
  }
  const complete = (name: string) => {
    setText(`/${name} `)
    ref.current?.focus()
  }

  const submit = async () => {
    const t = text.trim()
    const command = parseCommand(t)
    if (command) {
      // A bare "/co" with a menu open completes to the highlighted command first
      if (suggestions.length && !COMMAND_NAMES.has(command[0])) return complete(suggestions[Math.min(pick, suggestions.length - 1)].name)
      if (command[0] === 'help') return setText('/') // the full command menu
      // Cleared at once: a command can take a while (/compact), and text left in the box looks unsent
      setText('')
      if (await onCommand(command[0], command[1])) return
      setText(t) // not a command after all: it's sent as a message below
    }
    if (busy) return
    if (!t || !model) return
    setText('')
    releasePreviews(files)
    setFiles([])
    void onSend(t, files)
    ref.current?.focus()
  }

  return (
    <div
      className={cn(s.composer, (streaming || busy) && s.streaming, dragging && s.dragging)}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('Files')) {
          e.preventDefault()
          setDragging(true)
        }
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false)
      }}
      onDrop={onDrop}
    >
      {busy && (
        <div className={s.busy} role="status">
          <Spinner size={12} />
          {busy}
        </div>
      )}
      {queued.length > 0 && (
        <div className={s.queue}>
          <div className={s.queueHead}>
            <CornerDownRight size={12} />
            {queuePaused ? 'On hold — sent after you resume' : 'Up next — sent when the current reply finishes'}
            {queuePaused && !streaming && (
              <Button size="sm" variant="ghost" onClick={onResumeQueue} className={s.queueResume}>
                Send queued
              </Button>
            )}
          </div>
          {queued.map((q) => (
            <div key={q.id} className={s.queueItem}>
              <span>{q.text}</span>
              {q.files.length > 0 && <Paperclip size={11} />}
              <IconButton label="Remove from queue" icon={<X />} size="sm" onClick={() => onRemoveQueued(q.id)} />
            </div>
          ))}
        </div>
      )}
      {suggestions.length > 0 && (
        <div className={s.commands} role="listbox" aria-label="Commands">
          {suggestions.map((c, i) => (
            <button
              key={c.name}
              role="option"
              aria-selected={i === pick}
              className={cn(s.command, i === pick && s.commandOn)}
              onMouseEnter={() => setPick(i)}
              onClick={() => complete(c.name)}
            >
              <span className={s.commandName}>
                /{c.name}
                {c.args && <span className={s.commandArgs}> {c.args}</span>}
              </span>
              <span className={s.commandDesc}>{c.description}</span>
            </button>
          ))}
        </div>
      )}
      {files.length > 0 && (
        <div className={s.files}>
          {files.map((f, i) =>
            isImage(f) ? (
              <Thumb
                key={`${f.name}-${i}`}
                file={f}
                onRemove={() => {
                  releasePreviews([f])
                  setFiles(files.filter((_, j) => j !== i))
                }}
              />
            ) : (
              <span key={`${f.name}-${i}`} className={s.fileChip}>
                <Paperclip size={11} />
                <span className={s.fileName}>{f.name}</span>
                <span className={s.fileSize}>{formatBytes(f.size)}</span>
                <button aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}>
                  <X size={11} />
                </button>
              </span>
            ),
          )}
        </div>
      )}
      {blind && (
        <p className={s.visionNote}>
          <EyeOff size={12} />
          {mode === 'agent'
            ? `${current.name} can't see images — the agent will have a vision model describe them.`
            : `${current.name} can't see images — pick a vision model to ask about them.`}
        </p>
      )}
      <Textarea
        ref={ref}
        autoResize
        minRows={1}
        maxRows={12}
        value={text}
        placeholder={mode === 'agent' ? 'Ask the agent to set something up, generate, or explain… (/ for commands)' : 'Message… (/ for commands)'}
        className={s.input}
        onChange={(e) => setText(e.target.value)}
        onPaste={onPaste}
        onKeyDown={(e) => {
          if (suggestions.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
            e.preventDefault()
            setPick((p) => (p + (e.key === 'ArrowDown' ? 1 : suggestions.length - 1)) % suggestions.length)
            return
          }
          if (suggestions.length && e.key === 'Tab') {
            e.preventDefault()
            complete(suggestions[Math.min(pick, suggestions.length - 1)].name)
            return
          }
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            void submit()
          }
        }}
        autoFocus
      />
      <div className={s.bar}>
        <SegmentedControl<AgentMode>
          size="sm"
          aria-label="Mode"
          value={mode}
          onValueChange={onModeChange}
          segments={[
            { value: 'agent', label: 'Agent', icon: <Bot />, title: 'Can use tools' },
            { value: 'chat', label: 'Chat', icon: <MessageCircle />, title: 'No tools' },
          ]}
        />
        {groups.length > 0 ? (
          <div className={s.model}>
            <Select size="sm" value={model} onValueChange={onModelChange} options={groups} placeholder="Choose a model" />
          </div>
        ) : (
          <Link to="/models?tab=catalog&kind=text" className={s.noModels}>
            Install a language model →
          </Link>
        )}
        {noTools && <span className={s.warn}>This model can't call tools</span>}
        <div className={s.actions}>
          <ContextGauge usage={context} note={contextNote} />
          <IconButton
            label={verbose ? 'Verbose: on — thinking and tool steps shown expanded' : 'Verbose: off — show thinking and tool steps expanded'}
            icon={<Eye />}
            active={verbose}
            onClick={() => setVerbose(!verbose)}
          />
          <input
            ref={picker}
            type="file"
            multiple
            hidden
            accept={mode === 'agent' ? undefined : 'image/*'}
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []))
              e.target.value = ''
            }}
          />
          <IconButton
            label={mode === 'agent' ? 'Attach images or files (or paste / drop them)' : 'Attach images (or paste / drop them)'}
            icon={mode === 'agent' ? <Paperclip /> : <ImagePlus />}
            onClick={() => picker.current?.click()}
          />
          {streaming && <IconButton label="Stop" icon={<Square fill="currentColor" />} variant="secondary" onClick={onStop} />}
          {(!streaming || text.trim()) && (
            <IconButton
              label={streaming ? 'Queue as follow-up (Enter)' : 'Send (Enter)'}
              icon={streaming ? <ListPlus /> : <ArrowUp />}
              variant="primary"
              disabled={!text.trim() || !model}
              onClick={() => void submit()}
            />
          )}
        </div>
      </div>
    </div>
  )
}

/** A picture waiting to be sent, as a thumbnail. */
function Thumb({ file, onRemove }: { file: File; onRemove: () => void }) {
  return (
    <span className={s.thumb}>
      <img src={previewUrl(file)} alt={file.name} />
      <button aria-label={`Remove ${file.name}`} onClick={onRemove}>
        <X size={11} />
      </button>
    </span>
  )
}
