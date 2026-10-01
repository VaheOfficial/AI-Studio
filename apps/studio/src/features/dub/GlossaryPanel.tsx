import { useState } from 'react'
import { BookOpen, Check, Pencil, Plus, Sparkles, Trash2, X } from 'lucide-react'
import { Badge, Button, IconButton, Input } from '@studio/ui'
import type { DubGlossaryTerm } from '../../api/contracts/dub'
import { useGlossary, useGlossaryMutations } from './api'
import s from './Panels.module.css'

/** Project terminology (VoiceStudio `glossary-panel.tsx`): injected into every LLM translation prompt. */
export function GlossaryPanel({ projectId, lang, canAuto, onClose }: { projectId: string; lang: string; canAuto: boolean; onClose: () => void }) {
  const { data: terms = [] } = useGlossary(projectId)
  const m = useGlossaryMutations(projectId)
  const [draft, setDraft] = useState({ source: '', target: '', note: '' })
  const [editing, setEditing] = useState<string | null>(null)
  return (
    <section className={s.panel}>
      <header className={s.panelHead}>
        <BookOpen size={15} />
        <strong>Glossary</strong>
        <Badge size="sm">{terms.length}</Badge>
        <span className={s.panelHint}>Names and terms every translation must render the same way.</span>
        <Button size="sm" variant="secondary" iconLeft={<Sparkles />} disabled={!canAuto || !lang} loading={m.auto.isPending} onClick={() => m.auto.mutate(lang)}>
          Auto-extract
        </Button>
        <IconButton size="sm" label="Close glossary" icon={<X />} onClick={onClose} />
      </header>
      <div className={s.terms}>
        {terms.map((t) =>
          editing === t.id ? (
            <TermEditor key={t.id} term={t} onDone={() => setEditing(null)} onSave={(v) => m.update.mutate({ termId: t.id, ...v }, { onSuccess: () => setEditing(null) })} />
          ) : (
            <div key={t.id} className={s.term}>
              <span className={s.termSource}>{t.source}</span>
              <span className={s.arrow}>→</span>
              <span className={s.termTarget}>{t.target}</span>
              <span className={s.termNote}>{t.auto ? <Badge size="sm" tone="info">auto</Badge> : t.note}</span>
              <IconButton size="sm" label="Edit term" icon={<Pencil />} onClick={() => setEditing(t.id)} />
              <IconButton size="sm" label="Delete term" icon={<Trash2 />} onClick={() => m.remove.mutate(t.id)} />
            </div>
          ),
        )}
      </div>
      <div className={s.termForm}>
        <Input size="sm" placeholder="Term in the source" value={draft.source} onChange={(e) => setDraft({ ...draft, source: e.target.value })} />
        <Input size="sm" placeholder="Translation" value={draft.target} onChange={(e) => setDraft({ ...draft, target: e.target.value })} />
        <Input size="sm" placeholder="Note (optional)" value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} />
        <Button
          size="sm"
          variant="primary"
          iconLeft={<Plus />}
          disabled={!draft.source.trim() || !draft.target.trim()}
          loading={m.add.isPending}
          onClick={() => m.add.mutate(draft, { onSuccess: () => setDraft({ source: '', target: '', note: '' }) })}
        >
          Add term
        </Button>
      </div>
    </section>
  )
}

function TermEditor({ term, onSave, onDone }: { term: DubGlossaryTerm; onSave: (v: { source: string; target: string; note: string }) => void; onDone: () => void }) {
  const [v, setV] = useState({ source: term.source, target: term.target, note: term.note })
  return (
    <div className={s.termForm}>
      <Input size="sm" value={v.source} onChange={(e) => setV({ ...v, source: e.target.value })} />
      <Input size="sm" value={v.target} onChange={(e) => setV({ ...v, target: e.target.value })} />
      <Input size="sm" value={v.note} onChange={(e) => setV({ ...v, note: e.target.value })} />
      <span className={s.formActions}>
        <IconButton size="sm" label="Save" icon={<Check />} onClick={() => onSave(v)} />
        <IconButton size="sm" label="Cancel" icon={<X />} onClick={onDone} />
      </span>
    </div>
  )
}
