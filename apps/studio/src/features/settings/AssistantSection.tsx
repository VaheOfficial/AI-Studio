import { useState } from 'react'
import { Brain, Plus, Sparkles, Trash2 } from 'lucide-react'
import { Button, Field, IconButton, Input, SegmentedControl, Slider, Switch, Textarea } from '@studio/ui'
import { useAddMemory, useDeleteMemory, useMemories } from '../../api/hooks'
import type { Personality } from '../../api/types'
import { SettingsSection, type SettingsForm } from './form'
import s from './AssistantSection.module.css'

const PERSONALITIES: { value: Personality; label: string; hint: string }[] = [
  { value: 'friendly', label: 'Friendly', hint: 'Warm, curious and a little witty; casual in casual chats, plain paragraphs over heavy formatting.' },
  { value: 'default', label: 'Balanced', hint: 'Friendly and even-toned, with formatting where it helps.' },
  { value: 'efficient', label: 'Efficient', hint: 'Plain and brief: the answer first, no pleasantries.' },
]

const LENGTH_WORDS = ['', 'minimal', 'very short', 'short', 'concise', 'moderate', 'moderate', 'detailed', 'detailed', 'thorough', 'exhaustive']

/** How the chat assistant talks, what it's told about the user, and what it remembers (its system prompt). */
export function AssistantSection({ form }: { form: SettingsForm }) {
  const v = form.values
  const personality = PERSONALITIES.find((p) => p.value === v.assistant_personality) ?? PERSONALITIES[0]
  return (
    <SettingsSection
      icon={<Sparkles />}
      title="Assistant"
      description="How the chat assistant talks and what it knows about you. Applies to every chat, with any model."
    >
      <Field label="Personality" hint={personality.hint}>
        <SegmentedControl<Personality>
          value={v.assistant_personality}
          onValueChange={(p) => form.set('assistant_personality', p)}
          segments={PERSONALITIES.map((p) => ({ value: p.value, label: p.label }))}
        />
      </Field>
      <Field
        label="Answer length"
        aside={`${v.assistant_verbosity}/10 · ${LENGTH_WORDS[v.assistant_verbosity]}`}
        hint="The default. Asking for shorter or longer in a chat always wins, and research or 'teach me' questions get thorough answers."
      >
        <Slider
          aria-label="Answer length"
          value={v.assistant_verbosity}
          onValueChange={(n) => form.set('assistant_verbosity', n)}
          min={1}
          max={10}
          step={1}
        />
      </Field>
      <Field label="About you" hint="Your name, what you do, your setup, what you're working on. The assistant reads this in every chat.">
        {(id) => (
          <Textarea
            id={id}
            autoResize
            minRows={2}
            maxRows={8}
            maxLength={4000}
            placeholder="e.g. I'm a developer building a local AI studio on Windows; RTX 4090, 64 GB RAM."
            value={v.about_me}
            onChange={(e) => form.set('about_me', e.target.value)}
          />
        )}
      </Field>
      <Field label="Custom instructions" hint="How you want answers: tone, format, things to always or never do. These override the defaults.">
        {(id) => (
          <Textarea
            id={id}
            autoResize
            minRows={2}
            maxRows={10}
            maxLength={8000}
            placeholder="e.g. Use metric units. When I ask for code, show the whole file."
            value={v.custom_instructions}
            onChange={(e) => form.set('custom_instructions', e.target.value)}
          />
        )}
      </Field>
      <Switch
        label="Memory"
        description="Let the assistant remember facts about you across chats. It saves them itself when useful (or when you say “remember that…”); you can remove any of them here."
        checked={v.memory_enabled}
        onCheckedChange={(on) => form.set('memory_enabled', on)}
      />
      {v.memory_enabled && <MemoryList />}
    </SettingsSection>
  )
}

function MemoryList() {
  const { data: memories = [], isLoading } = useMemories()
  const add = useAddMemory()
  const del = useDeleteMemory()
  const [text, setText] = useState('')
  const submit = () => {
    const t = text.trim()
    if (!t) return
    add.mutate(t, { onSuccess: () => setText('') })
  }
  return (
    <div className={s.memory}>
      {memories.length > 0 ? (
        <ul className={s.list}>
          {memories.map((m) => (
            <li key={m.id} className={s.item}>
              <Brain size={13} className={s.itemIcon} />
              <span className={s.itemText}>{m.text}</span>
              <IconButton size="sm" label="Forget this" icon={<Trash2 />} onClick={() => del.mutate(m.id)} />
            </li>
          ))}
        </ul>
      ) : (
        !isLoading && <p className={s.empty}>Nothing remembered yet. Say “remember that…” in an Agent chat, or add something here.</p>
      )}
      <div className={s.add}>
        <Input
          aria-label="Add a memory"
          placeholder="Add something for the assistant to remember…"
          value={text}
          maxLength={500}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
        />
        <Button size="sm" variant="secondary" iconLeft={<Plus />} onClick={submit} disabled={!text.trim()} loading={add.isPending}>
          Add
        </Button>
      </div>
    </div>
  )
}
