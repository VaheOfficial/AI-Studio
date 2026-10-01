import { useEffect, useRef } from 'react'
import { Bot, FolderOpen, Plus, SquareTerminal, X } from 'lucide-react'
import { Button, EmptyState, IconButton, StatusDot, Terminal, cn, type TerminalHandle } from '@studio/ui'
import type { TerminalInfo } from '../../../api/contracts/workspace'
import { terminal, terminalOutput, useTerminals } from '../../../api/workspace'
import { useWorkspacePanel } from './panel'
import s from './TerminalTab.module.css'

/** One PTY: replays its scrollback, then streams live output; keystrokes go to the process. */
function TerminalView({ info, active }: { info: TerminalInfo; active: boolean }) {
  const ref = useRef<TerminalHandle>(null)
  useEffect(() => {
    ref.current?.write(terminalOutput.read(info.id))
    return terminalOutput.subscribe(info.id, (data) => ref.current?.write(data))
  }, [info.id])
  useEffect(() => {
    if (active) ref.current?.focus()
  }, [active])
  return (
    <div className={s.view} hidden={!active}>
      <Terminal ref={ref} onData={(d) => terminal.input(info.id, d)} onResize={(c, r) => terminal.resize(info.id, c, r)} />
      {info.status === 'exited' && (
        <div className={s.exited} data-ok={info.exit_code === 0 || undefined}>
          Process exited with code {info.exit_code}
        </div>
      )}
    </div>
  )
}

export function TerminalTab({ sessionId, root, onPickFolder }: { sessionId: string; root?: string; onPickFolder: () => void }) {
  const { data: terms = [], isFetched } = useTerminals(sessionId)
  const { terminalId, showTerminal } = useWorkspacePanel()
  const active = terms.find((t) => t.id === terminalId) ?? terms[terms.length - 1]

  // A terminal started while this chat is open (the user's or the agent's) becomes the active one;
  // the tab itself is not switched, so the user isn't pulled away from what they're looking at.
  const known = useRef<Set<string>>(undefined)
  useEffect(() => {
    if (!isFetched) return
    const ids = new Set(terms.map((t) => t.id))
    const fresh = known.current && terms.filter((t) => !known.current?.has(t.id)).pop()
    known.current = ids
    if (fresh) useWorkspacePanel.setState({ terminalId: fresh.id })
  }, [terms, isFetched])

  const open = () => terminal.open(sessionId, 120, 30)

  if (!root) {
    return (
      <EmptyState
        icon={<FolderOpen />}
        title="Choose a folder first"
        description="Terminals open in the chat's workspace folder."
        action={
          <Button variant="secondary" onClick={onPickFolder}>
            Choose folder
          </Button>
        }
      />
    )
  }

  return (
    <div className={s.tab}>
      <div className={s.strip} role="tablist" aria-label="Terminals">
        {terms.map((t) => (
          <div key={t.id} className={cn(s.chip, t.id === active?.id && s.chipActive)} role="tab" aria-selected={t.id === active?.id}>
            <button className={s.chipMain} onClick={() => showTerminal(t.id)} title={`${t.title}\n${t.cwd}`}>
              {t.kind === 'command' ? <Bot size={12} /> : <SquareTerminal size={12} />}
              <span>{t.title}</span>
              <StatusDot status={t.status === 'running' ? 'active' : t.exit_code === 0 ? 'off' : 'error'} />
            </button>
            <button className={s.chipClose} aria-label={`Close ${t.title}`} onClick={() => terminal.close(t.id)}>
              <X size={11} />
            </button>
          </div>
        ))}
        <IconButton label="New terminal" icon={<Plus />} size="sm" onClick={open} />
      </div>
      {terms.length === 0 ? (
        <EmptyState
          icon={<SquareTerminal />}
          title="No terminals yet"
          description="Open a PowerShell here, or ask the agent to run something — its commands appear as tabs you can watch and type into."
          action={
            <Button variant="secondary" iconLeft={<Plus />} onClick={open}>
              New terminal
            </Button>
          }
        />
      ) : (
        <div className={s.views}>
          {terms.map((t) => (
            <TerminalView key={t.id} info={t} active={t.id === active?.id} />
          ))}
        </div>
      )}
    </div>
  )
}
