import type { ReactNode } from 'react'
import { BookOpen, Check, Coins, Dices, FlaskConical, KeyRound, MapPin, Package, Scroll, Shield, Skull, Sword, X } from 'lucide-react'
import { Badge, Button, Progress, Tooltip, cn } from '@studio/ui'
import type { GameItem, GameItemKind, GameState } from '../../api/contracts/game'
import s from './CharacterSheet.module.css'

const KIND_ICON: Record<GameItemKind, ReactNode> = {
  weapon: <Sword size={14} />,
  armor: <Shield size={14} />,
  consumable: <FlaskConical size={14} />,
  key: <KeyRound size={14} />,
  misc: <Package size={14} />,
}
const STATS = [
  ['strength', 'STR'],
  ['dexterity', 'DEX'],
  ['intelligence', 'INT'],
  ['charisma', 'CHA'],
] as const

const modifier = (v: number) => Math.floor((v - 10) / 2)
const signed = (n: number) => (n >= 0 ? `+${n}` : String(n))

/** The authoritative state kept by the server; inventory buttons play the matching action. */
export function CharacterSheet({ state, disabled, onAction }: { state: GameState; disabled: boolean; onAction: (text: string) => void }) {
  const p = state.player
  const hp = p.max_hp ? p.hp / p.max_hp : 0
  const quests = [...state.quests].sort((a, b) => Number(a.status !== 'active') - Number(b.status !== 'active'))
  return (
    <aside className={s.sheet}>
      <section className={s.hero}>
        <div className={s.nameRow}>
          <strong className={s.name}>{p.name}</strong>
          <Badge size="sm" tone="neutral">
            Lv {p.level} {p.role}
          </Badge>
        </div>
        <Meter label="HP" value={`${p.hp} / ${p.max_hp}`}>
          <Progress value={hp} tone={hp <= 0.3 ? 'danger' : hp <= 0.6 ? 'warning' : 'success'} aria-label="Health" />
        </Meter>
        <Meter label="XP" value={`${p.xp} / ${p.xp_next}`}>
          <Progress value={p.xp_next ? p.xp / p.xp_next : 0} size="xs" aria-label="Experience" />
        </Meter>
        <div className={s.goldRow}>
          <span className={s.gold}>
            <Coins size={14} /> {p.gold} gold
          </span>
          <Tooltip
            content={
              state.dice_bag.length
                ? `Your d20 is a bag: rolls are drawn without repeats, and it refills at 4 left. Still in the bag: ${[...state.dice_bag].sort((a, b) => a - b).join(', ')}`
                : 'Your d20 is a bag: rolls are drawn without repeats, and it refills at 4 left.'
            }
          >
            <span className={s.bag}>
              <Dices size={13} /> {state.dice_bag.length || 20} in bag
            </span>
          </Tooltip>
        </div>
        <div className={s.stats}>
          {STATS.map(([key, label]) => (
            <Tooltip key={key} content={`${key[0].toUpperCase()}${key.slice(1)} ${p.stats[key]} (modifier ${signed(modifier(p.stats[key]))})`}>
              <div className={s.stat}>
                <span className={s.statLabel}>{label}</span>
                <span className={s.statValue}>{p.stats[key]}</span>
                <span className={s.statMod}>{signed(modifier(p.stats[key]))}</span>
              </div>
            </Tooltip>
          ))}
        </div>
        {p.conditions.length > 0 && (
          <div className={s.tags}>
            {p.conditions.map((c) => (
              <Badge key={c} size="sm" tone="warning">
                {c}
              </Badge>
            ))}
          </div>
        )}
      </section>

      {state.enemies.length > 0 && (
        <Section title="Encounter" icon={<Skull size={13} />} tone="danger">
          {state.enemies.map((e) => (
            <Tooltip key={e.id} content={e.description || e.name}>
              <div className={s.enemy}>
                <div className={s.enemyHead}>
                  <span>{e.name}</span>
                  <span className={s.num}>
                    {e.hp} / {e.max_hp}
                  </span>
                </div>
                <Progress value={e.max_hp ? e.hp / e.max_hp : 0} size="xs" tone="danger" aria-label={`${e.name} health`} />
              </div>
            </Tooltip>
          ))}
        </Section>
      )}

      <Section title="Location" icon={<MapPin size={13} />}>
        <strong className={s.place}>{state.location.name}</strong>
        {state.location.description && <p className={s.muted}>{state.location.description}</p>}
      </Section>

      <Section title="Quests" icon={<Scroll size={13} />}>
        {quests.length === 0 ? (
          <p className={s.muted}>None yet.</p>
        ) : (
          quests.map((q) => (
            <div key={q.id} className={cn(s.quest, q.status !== 'active' && s.questDone)}>
              <span className={s.questIcon}>{q.status === 'done' ? <Check size={13} /> : q.status === 'failed' ? <X size={13} /> : '•'}</span>
              <div>
                <div className={s.questTitle}>{q.title}</div>
                {q.status === 'active' && q.notes && <p className={s.muted}>{q.notes}</p>}
              </div>
            </div>
          ))
        )}
      </Section>

      <Section title={`Inventory · ${state.inventory.length}`} icon={<Package size={13} />}>
        {state.inventory.length === 0 ? (
          <p className={s.muted}>Empty.</p>
        ) : (
          state.inventory.map((item) => <ItemRow key={item.id} item={item} disabled={disabled} onAction={onAction} />)
        )}
      </Section>

      {(state.summary || state.chronicle.length > 0) && (
        <Section title="Journal" icon={<BookOpen size={13} />}>
          <p className={s.muted}>What the game remembers — it's all the game master needs, however long the adventure runs.</p>
          {state.summary && <p className={s.journalSummary}>{state.summary}</p>}
          <ol className={s.journal}>
            {state.chronicle.map((entry, i) => (
              <li key={i}>{entry}</li>
            ))}
          </ol>
        </Section>
      )}
    </aside>
  )
}

function ItemRow({ item, disabled, onAction }: { item: GameItem; disabled: boolean; onAction: (text: string) => void }) {
  const gear = item.kind === 'weapon' || item.kind === 'armor'
  const power = item.power != null && (item.kind === 'armor' ? `${item.power} def` : item.kind === 'consumable' ? `+${item.power}` : `${item.power} dmg`)
  return (
    <div className={s.item}>
      <Tooltip content={item.description || item.name}>
        <div className={s.itemMain}>
          <span className={cn(s.itemIcon, item.equipped && s.itemEquipped)}>{KIND_ICON[item.kind]}</span>
          <span className={s.itemName}>
            {item.name}
            {item.qty > 1 && <span className={s.qty}> ×{item.qty}</span>}
          </span>
          {power && <span className={s.power}>{power}</span>}
          {item.equipped && (
            <Badge size="sm" tone="accent">
              Equipped
            </Badge>
          )}
        </div>
      </Tooltip>
      {item.kind === 'consumable' && (
        <Button size="sm" variant="ghost" disabled={disabled} onClick={() => onAction(`Use the ${item.name}`)}>
          Use
        </Button>
      )}
      {gear && !item.equipped && (
        <Button size="sm" variant="ghost" disabled={disabled} onClick={() => onAction(`Equip the ${item.name}`)}>
          Equip
        </Button>
      )}
    </div>
  )
}

function Meter({ label, value, children }: { label: string; value: string; children: ReactNode }) {
  return (
    <div className={s.meter}>
      <div className={s.meterHead}>
        <span>{label}</span>
        <span className={s.num}>{value}</span>
      </div>
      {children}
    </div>
  )
}

function Section({ title, icon, tone, children }: { title: string; icon: ReactNode; tone?: 'danger'; children: ReactNode }) {
  return (
    <section className={cn(s.section, tone === 'danger' && s.sectionDanger)}>
      <h3 className={s.sectionTitle}>
        {icon}
        {title}
      </h3>
      {children}
    </section>
  )
}
