import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { motion } from 'motion/react'
import { ArrowUp, ChevronsRight, Dices, FlaskConical, Footprints, Headphones, Shield, Skull, Square, Sword, Swords, Trophy, Undo2 } from 'lucide-react'
import { Button, EmptyState, IconButton, Kbd, Select, Skeleton, Textarea, Tooltip, cn } from '@studio/ui'
import type { CombatRequest, CombatRoll, Game, GamePending, GameState, GameTurn } from '../../api/contracts/game'
import { useCombat, useGame, useGameAction, useMakeMedia, usePatchGame, useStopTurn, useUndoTurn } from '../../api/game'
import { useChatModels } from '../../api/hooks'
import { Markdown } from '../chat/Markdown'
import { CharacterSheet } from './CharacterSheet'
import { MusicControl, TurnMedia } from './Media'
import { useGamePrefs } from './prefs'
import s from './GameView.module.css'

export function GameView({ id }: { id: string }) {
  const { data: game, isLoading, error } = useGame(id)
  const act = useGameAction(id)
  const fight = useCombat(id)
  const makeMedia = useMakeMedia(id)
  const autoRead = useGamePrefs((st) => st.autoRead)
  // Turns that arrive while the game is open are "live": narrated automatically when auto-read is on
  const [firstSeen, setFirstSeen] = useState<string | null | undefined>(undefined)
  const newest = game?.turns.at(-1)
  if (game && firstSeen === undefined) setFirstSeen(newest?.id ?? null)
  const liveTurn = newest && firstSeen !== undefined && newest.id !== firstSeen ? newest.id : undefined
  const narrated = useRef(new Set<string>())
  const narrate = makeMedia.mutate
  useEffect(() => {
    if (!autoRead || !liveTurn || narrated.current.has(liveTurn)) return
    narrated.current.add(liveTurn)
    narrate({ kind: 'audio', turnId: liveTurn })
  }, [autoRead, liveTurn, narrate])
  if (isLoading) {
    return (
      <div className={s.loading}>
        <Skeleton height={20} width="40%" />
        <Skeleton height={120} />
        <Skeleton height={20} width="60%" />
      </div>
    )
  }
  if (error || !game) return <EmptyState icon={<Swords />} title="Adventure not found" description={error?.message ?? 'It may have been deleted.'} />
  const busy = !!game.pending || act.isPending || fight.isPending
  const playing = game.state.status === 'playing'
  const send = (text: string) => {
    const action = text.trim()
    if (action && !busy && playing) act.mutate(action)
  }
  return (
    <div className={s.view}>
      <div className={s.main}>
        <Header game={game} />
        <Story game={game} liveTurn={autoRead ? liveTurn : undefined} />
        {playing ? (
          <>
            {game.state.enemies.length > 0 && <CombatBar state={game.state} busy={busy} onFight={(req) => fight.mutate(req)} />}
            <ActionBar choices={game.pending ? [] : (game.turns.at(-1)?.choices ?? [])} busy={busy} running={!!game.pending} gameId={game.id} onSend={send} />
          </>
        ) : (
          <GameOver game={game} />
        )}
      </div>
      <CharacterSheet state={game.state} disabled={busy || !playing} onAction={send} />
    </div>
  )
}

function Header({ game }: { game: Game }) {
  const undo = useUndoTurn(game.id)
  const patch = usePatchGame(game.id)
  const { data: models = [] } = useChatModels()
  const options = models.filter((m) => m.available || m.id === game.model).map((m) => ({ value: m.id, label: m.name }))
  return (
    <header className={s.header}>
      <div className={s.titleBlock}>
        <h1 className={s.title}>{game.title}</h1>
        <span className={s.location}>{game.state.location.name}</span>
      </div>
      <MusicControl game={game} />
      <AutoRead />
      <div className={s.model}>
        <Select size="sm" value={game.model} onValueChange={(model) => patch.mutate({ model })} options={options} />
      </div>
      <IconButton
        label="Undo last turn"
        icon={<Undo2 />}
        disabled={!!game.pending || game.turns.length <= 1 || undo.isPending}
        onClick={() => undo.mutate(undefined)}
      />
    </header>
  )
}

/** The story, following its end while it grows unless the player has scrolled up to reread. */
function AutoRead() {
  const on = useGamePrefs((st) => st.autoRead)
  const set = useGamePrefs((st) => st.setAutoRead)
  return (
    <IconButton
      label={on ? 'Auto-read: on — new turns are narrated aloud' : 'Auto-read: off — narrate new turns aloud'}
      icon={<Headphones />}
      active={on}
      onClick={() => set(!on)}
    />
  )
}

function Story({ game, liveTurn }: { game: Game; liveTurn?: string }) {
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const toEnd = () => {
    const el = scroller.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }
  useLayoutEffect(toEnd, [game.turns.length, game.pending?.narration])
  const follow = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    toEnd()
    const ro = new ResizeObserver(toEnd)
    ro.observe(node)
    return () => ro.disconnect()
  }, [])
  return (
    <div
      ref={scroller}
      className={s.story}
      onScroll={(e) => {
        const el = e.currentTarget
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
      }}
    >
      <div ref={follow} className={s.storyInner}>
        {game.turns.map((t, i) => (
          <TurnView key={t.id} gameId={game.id} turn={t} opening={i === 0} autoPlay={t.id === liveTurn} />
        ))}
        {game.pending && <PendingTurn pending={game.pending} opening={game.turns.length === 0} />}
      </div>
    </div>
  )
}

function ActionLine({ action, roll }: { action: string; roll?: number }) {
  return (
    <div className={s.action}>
      <ChevronsRight size={14} />
      <span className={s.actionText}>{action}</span>
      {roll != null && (
        <span className={cn(s.roll, roll === 20 && s.crit, roll === 1 && s.fumble)} title="Your d20 roll for this action">
          <Dices size={12} /> {roll}
        </span>
      )}
    </div>
  )
}

function CombatLog({ rolls }: { rolls: CombatRoll[] }) {
  if (!rolls.length) return null
  return (
    <div className={s.combatLog}>
      {rolls.map((r, i) => (
        <div key={i} className={cn(s.combatRow, r.hit ? s.combatHit : s.combatMiss)}>
          <span className={s.combatWho}>{r.target === 'escape' ? `${r.actor} flees` : `${r.actor} → ${r.target}`}</span>
          <span className={s.combatMath}>
            <Dices size={11} /> {r.roll}
            {r.bonus >= 0 ? '+' : ''}
            {r.bonus} = {r.total} vs {r.target === 'escape' ? 'DC' : 'AC'} {r.against}
          </span>
          <span className={s.combatResult}>
            {r.target === 'escape' ? (r.hit ? 'escaped' : 'cornered') : r.hit ? `hit, ${r.damage} dmg` : 'miss'}
            {r.note && r.note !== 'escaped' && r.note !== 'cornered' && ` · ${r.note}`}
          </span>
        </div>
      ))}
    </div>
  )
}

function TurnView({ gameId, turn, opening, autoPlay }: { gameId: string; turn: GameTurn; opening: boolean; autoPlay: boolean }) {
  return (
    <motion.article className={s.turn} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      {opening ? <div className={s.opening}>The adventure begins</div> : <ActionLine action={turn.action} roll={turn.roll} />}
      <CombatLog rolls={turn.combat} />
      <div className={s.narration}>
        <Markdown text={turn.narration} />
      </div>
      {turn.changes.length > 0 && (
        <div className={s.changes}>
          {turn.changes.map((c, i) => (
            <span key={i} className={cn(s.change, s[c.tone])}>
              {c.text}
            </span>
          ))}
        </div>
      )}
      <TurnMedia gameId={gameId} turn={turn} autoPlay={autoPlay} />
    </motion.article>
  )
}

function PendingTurn({ pending, opening }: { pending: GamePending; opening: boolean }) {
  return (
    <article className={s.turn}>
      {opening ? <div className={s.opening}>The adventure begins</div> : <ActionLine action={pending.action} roll={pending.roll} />}
      <CombatLog rolls={pending.combat} />
      <div className={s.narration}>
        {pending.narration.trim() ? <Markdown text={pending.narration} /> : <p className={s.writing}>The game master is writing…</p>}
      </div>
    </article>
  )
}

function ActionBar({ choices, busy, running, gameId, onSend }: { choices: string[]; busy: boolean; running: boolean; gameId: string; onSend: (text: string) => void }) {
  const [text, setText] = useState('')
  const stop = useStopTurn(gameId)
  const submit = () => {
    if (!text.trim() || busy) return
    onSend(text)
    setText('')
  }
  // 1-4 pick a suggestion (unless typing)
  const latest = useRef({ choices, busy, onSend })
  useEffect(() => {
    latest.current = { choices, busy, onSend }
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (e.ctrlKey || e.metaKey || e.altKey || target.closest('input, textarea, [contenteditable="true"]')) return
      const { choices: list, busy: b, onSend: go } = latest.current
      const choice = list[Number(e.key) - 1]
      if (choice && !b) {
        e.preventDefault()
        go(choice)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  return (
    <div className={s.bar}>
      {choices.length > 0 && (
        <div className={s.choices}>
          {choices.map((c, i) => (
            <button key={c} type="button" className={s.choice} disabled={busy} onClick={() => onSend(c)}>
              <Kbd>{i + 1}</Kbd>
              <span>{c}</span>
            </button>
          ))}
        </div>
      )}
      <div className={s.inputRow}>
        <Textarea
          autoResize
          minRows={1}
          maxRows={5}
          value={text}
          className={s.input}
          placeholder={running ? 'The game master is writing…' : 'Or do anything else — describe it…'}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              submit()
            }
          }}
        />
        {running ? (
          <IconButton label="Stop the game master" icon={<Square />} variant="secondary" onClick={() => stop.mutate(undefined)} />
        ) : (
          <IconButton label="Act (Enter)" icon={<ArrowUp />} variant="primary" disabled={!text.trim() || busy} onClick={submit} />
        )}
      </div>
    </div>
  )
}

/** Fight with the rules: attack an enemy, defend, flee or drink something — settled by the dice, then narrated. */
function CombatBar({ state, busy, onFight }: { state: GameState; busy: boolean; onFight: (req: CombatRequest) => void }) {
  const consumables = state.inventory.filter((i) => i.kind === 'consumable')
  const [item, setItem] = useState<string>()
  const chosen = consumables.find((i) => i.name === item) ?? consumables[0]
  return (
    <div className={s.combatBar}>
      <span className={s.combatLabel}>
        <Swords size={13} /> Combat
      </span>
      {state.enemies.map((e) => (
        <Tooltip key={e.id} content={`${e.description || e.name} — AC ${e.ac}, attack +${e.attack}, hits for ~${e.damage}`}>
          <Button size="sm" variant="secondary" iconLeft={<Sword />} disabled={busy} onClick={() => onFight({ kind: 'attack', target: e.id })}>
            {e.name} <span className={s.combatHp}>{e.hp}/{e.max_hp}</span>
          </Button>
        </Tooltip>
      ))}
      <Tooltip content="+4 armor class against this round's attacks">
        <Button size="sm" variant="ghost" iconLeft={<Shield />} disabled={busy} onClick={() => onFight({ kind: 'defend' })}>
          Defend
        </Button>
      </Tooltip>
      <Tooltip content="A dexterity roll against 12 — fail and they get their attacks">
        <Button size="sm" variant="ghost" iconLeft={<Footprints />} disabled={busy} onClick={() => onFight({ kind: 'flee' })}>
          Flee
        </Button>
      </Tooltip>
      {consumables.length > 0 && (
        <div className={s.combatItem}>
          {consumables.length > 1 && (
            <Select
              size="sm"
              value={chosen?.name}
              onValueChange={setItem}
              options={consumables.map((i) => ({ value: i.name, label: `${i.name}${i.qty > 1 ? ` ×${i.qty}` : ''}` }))}
            />
          )}
          <Button size="sm" variant="ghost" iconLeft={<FlaskConical />} disabled={busy || !chosen} onClick={() => chosen && onFight({ kind: 'item', item: chosen.name })}>
            {consumables.length > 1 ? 'Use' : `Use ${chosen?.name}`}
          </Button>
        </div>
      )}
    </div>
  )
}

function GameOver({ game }: { game: Game }) {
  const navigate = useNavigate()
  const undo = useUndoTurn(game.id)
  const won = game.state.status === 'won'
  return (
    <div className={cn(s.over, won ? s.overWon : s.overDead)}>
      {won ? <Trophy /> : <Skull />}
      <div className={s.overText}>
        <strong>{won ? 'Victory!' : 'You have fallen.'}</strong>
        <span>{won ? 'The adventure is complete.' : 'Take the last turn back and choose differently, or begin anew.'}</span>
      </div>
      {!won && (
        <Button variant="secondary" iconLeft={<Undo2 />} loading={undo.isPending} onClick={() => undo.mutate(undefined)}>
          Undo last turn
        </Button>
      )}
      <Button variant="primary" iconLeft={<Swords />} onClick={() => navigate('/game')}>
        New adventure
      </Button>
    </div>
  )
}
