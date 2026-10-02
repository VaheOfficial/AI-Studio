import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { motion } from 'motion/react'
import { Anchor, Castle, Cpu, Eye, PenLine, Radiation, Rocket, Skull, Sparkles, Swords } from 'lucide-react'
import { Button, ChipGroup, Field, Input, Select, Textarea, cn } from '@studio/ui'
import { useNewGame } from '../../api/game'
import { useChatModels, useSettings } from '../../api/hooks'
import s from './NewGame.module.css'

/** World premises the game master builds on (or the player's own). */
const WORLDS = [
  { id: 'dark', label: 'Dark fantasy', text: 'A grim, war-torn kingdom where old gods stir, monsters haunt the roads and every coin is hard-won.' },
  { id: 'high', label: 'High fantasy', text: 'A bright world of elves, dwarves, dragons and ancient magic, on the eve of a great quest.' },
  { id: 'scifi', label: 'Space opera', text: 'A frontier star system of smugglers, alien ruins and a failing galactic empire.' },
  { id: 'cyber', label: 'Cyberpunk', text: 'A rain-soaked megacity ruled by corporations, where implants, hackers and street gangs collide.' },
  { id: 'post', label: 'Post-apocalyptic', text: 'Decades after the collapse: scavengers, mutated beasts and scattered settlements fighting over clean water.' },
  { id: 'horror', label: 'Cosmic horror', text: '1920s New England. A missing professor, a fog-bound town and things that should not exist.' },
  { id: 'pirate', label: 'Pirates', text: 'A sun-bleached archipelago of pirate havens, naval patrols, cursed treasure and sea monsters.' },
  { id: 'custom', label: 'Your own', text: '' },
] as const

/** Each world's emblem and color on its card. */
const WORLD_LOOK: Record<(typeof WORLDS)[number]['id'], { icon: ReactNode; hue: string }> = {
  dark: { icon: <Skull />, hue: 'var(--brand)' },
  high: { icon: <Castle />, hue: 'var(--accent-2)' },
  scifi: { icon: <Rocket />, hue: 'var(--hue-stt)' },
  cyber: { icon: <Cpu />, hue: 'var(--hue-music)' },
  post: { icon: <Radiation />, hue: 'var(--hue-game)' },
  horror: { icon: <Eye />, hue: 'var(--hue-video)' },
  pirate: { icon: <Anchor />, hue: 'var(--hue-voice)' },
  custom: { icon: <PenLine />, hue: 'var(--text-2)' },
}

const ROLES = ['Warrior', 'Rogue', 'Mage', 'Ranger', 'Custom'] as const
const ROLE_HINT: Record<string, string> = {
  Warrior: 'Strong and tough — 32 HP, high strength.',
  Rogue: 'Quick and sly — 24 HP, high dexterity.',
  Mage: 'Clever and fragile — 20 HP, high intelligence.',
  Ranger: 'Nimble tracker — 26 HP, dexterity and strength.',
  Custom: 'Any class you like, with balanced stats — 26 HP.',
}

export function NewGame() {
  const navigate = useNavigate()
  const create = useNewGame()
  const { data: models = [] } = useChatModels()
  const { data: settings } = useSettings()
  const [world, setWorld] = useState<(typeof WORLDS)[number]['id']>('dark')
  const [customWorld, setCustomWorld] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<(typeof ROLES)[number]>('Warrior')
  const [customRole, setCustomRole] = useState('')
  const [model, setModel] = useState<string>()
  const available = models.filter((m) => m.available)
  const chosenModel = model ?? settings?.default_chat_model ?? available[0]?.id
  const setting = world === 'custom' ? customWorld.trim() : WORLDS.find((w) => w.id === world)!.text
  const className = role === 'Custom' ? customRole.trim() : role
  const ready = !!chosenModel && setting.length >= 3 && !!name.trim() && !!className

  const start = () => {
    if (!ready) return
    create.mutate(
      { model: chosenModel!, setting, name: name.trim(), role: className },
      { onSuccess: (game) => navigate(`/game/${game.id}`) },
    )
  }

  return (
    <div className={s.wrap}>
      <motion.div className={s.card} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}>
        <div className={s.head}>
          <span className={s.icon}>
            <Swords />
          </span>
          <div>
            <h1 className={s.title}>New adventure</h1>
            <p className={s.sub}>An AI game master tells the story; the game keeps your character, inventory and quests, so nothing is forgotten.</p>
          </div>
        </div>

        <section className={s.section}>
          <h2 className={s.label}>World</h2>
          <div className={`${s.worlds} ui-stagger`}>
            {WORLDS.map((w) => (
              <button
                key={w.id}
                type="button"
                className={cn(s.world, world === w.id && s.worldActive)}
                style={{ ['--world' as string]: WORLD_LOOK[w.id].hue }}
                onClick={() => setWorld(w.id)}
                aria-pressed={world === w.id}
              >
                <i className={s.worldIcon}>{WORLD_LOOK[w.id].icon}</i>
                <strong>{w.label}</strong>
                {w.text && <span>{w.text}</span>}
                {!w.text && <span>Describe any setting you want.</span>}
              </button>
            ))}
          </div>
          {world === 'custom' && (
            <Textarea
              autoResize
              minRows={2}
              maxRows={6}
              value={customWorld}
              onChange={(e) => setCustomWorld(e.target.value)}
              placeholder="e.g. A floating city of clockwork islands where the sky itself is running out of air…"
              aria-label="Your world"
            />
          )}
        </section>

        <section className={s.row}>
          <Field label="Your character's name">
            {(id) => <Input id={id} value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="e.g. Aria" />}
          </Field>
          <Field label="Game master (chat model)">
            {(id) => (
              <Select
                id={id}
                value={chosenModel}
                onValueChange={setModel}
                placeholder="Install a chat model first"
                options={available.map((m) => ({ value: m.id, label: m.name }))}
              />
            )}
          </Field>
        </section>

        <section className={s.section}>
          <h2 className={s.label}>Class</h2>
          <ChipGroup value={role} onValueChange={setRole} chips={ROLES.map((r) => ({ value: r, label: r, color: 'var(--hue-game)' }))} aria-label="Class" />
          <p className={s.hint}>{ROLE_HINT[role]}</p>
          {role === 'Custom' && (
            <Input value={customRole} maxLength={60} onChange={(e) => setCustomRole(e.target.value)} placeholder="e.g. Necromancer, Bounty hunter, Bard" aria-label="Custom class" />
          )}
        </section>

        <Button variant="primary" size="lg" iconLeft={<Sparkles />} disabled={!ready} loading={create.isPending} onClick={start} className={s.start}>
          Begin the adventure
        </Button>
      </motion.div>
    </div>
  )
}
