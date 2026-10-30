import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { Badge, Button, Field, Select, Textarea, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useAgentArtifacts, useAgentMutation } from '../../api/agents'
import type { AgentArtifact, ArtifactCreate, ArtifactRevision } from '../../api/contracts/agents'
import { Markdown } from '../chat/Markdown'
import s from './AgentsPage.module.css'

const CSP = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; font-src data:; connect-src \'none\'; form-action \'none\'; base-uri \'none\'">'

export default function ArtifactsPanel() {
  const { data, error } = useAgentArtifacts()
  const [selected, setSelected] = useState<AgentArtifact>()
  const [content, setContent] = useState('')
  const [revision, setRevision] = useState('current')
  const { data: history } = useQuery({ queryKey: ['agents', 'artifact-history', selected?.id, selected?.version], enabled: !!selected,
    queryFn: () => api.get<ArtifactRevision[]>(`/agents/artifacts/${selected!.id}/history`) })
  const save = useAgentMutation((a: { sid: string; body: ArtifactCreate }) => api.post<AgentArtifact>(`/agents/sessions/${a.sid}/artifacts`, a.body))
  const load = useAgentMutation((a: { id: string; version: number }) => api.get<AgentArtifact>(`/agents/artifacts/${a.id}?version=${a.version}`))
  const err = (e: Error) => toast.error('Artifact operation could not be completed', e.message)
  return <section className={s.panel}><h2>Editable artifacts</h2><p>Review earlier revisions, edit the source and export an output. Saving creates a new revision.</p>{error && <p>{error.message}</p>}
    <Field label="Artifact"><Select aria-label="Artifact" value={selected?.id ?? ''} placeholder="Choose an artifact" options={(data ?? []).map(a => ({ value: a.id, label: `${a.title} · v${a.version}` }))} onValueChange={id => { const a = data?.find(v => v.id === id); setSelected(a); setContent(a?.content ?? ''); setRevision('current') }} /></Field>
    {selected && <><div className={s.actions}><Badge>{selected.kind}</Badge><Link to={`/agents/chat/${selected.session_id}`}>Open conversation</Link>
      <a href={`/api/agents/artifacts/${selected.id}/export${revision === 'current' ? '' : `?version=${revision}`}`} download>Export saved revision</a>
      <Button disabled={save.isPending || load.isPending} onClick={() => save.mutate({ sid: selected.session_id, body: { id: selected.id, version: selected.version, title: selected.title, kind: selected.kind, content } }, { onSuccess: a => { setSelected(a); setRevision('current') }, onError: err })}>Save revision</Button></div>
      <Select aria-label="Artifact revision" value={revision} options={[{ value: 'current', label: `Current revision · v${selected.version}` }, ...(history ?? []).filter(v => v.version !== selected.version).map(v => ({ value: String(v.version), label: `v${v.version} · ${v.updated_at}` }))]} onValueChange={v => {
        if (v === 'current') { setRevision(v); setContent(selected.content) }
        else load.mutate({ id: selected.id, version: Number(v) }, { onSuccess: a => { setRevision(v); setContent(a.content) }, onError: err })
      }} />
      <Field label="Artifact source"><Textarea aria-label="Artifact source" value={content} onChange={e => setContent(e.target.value)} rows={14} /></Field>
      {selected.kind === 'html' ? <iframe className={s.preview} title={selected.title} sandbox="allow-scripts" referrerPolicy="no-referrer" srcDoc={CSP + content} /> : selected.kind === 'markdown' ? <Markdown text={content} /> : <pre>{content}</pre>}
    </>}
    {!data?.length && <p className={s.empty}>Ask your agent to create a document, page or other artifact. Saved work will appear here.</p>}
  </section>
}
