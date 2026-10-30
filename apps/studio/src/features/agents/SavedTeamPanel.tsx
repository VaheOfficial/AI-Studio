import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Badge, Select } from '@studio/ui'
import { api } from '../../api/client'
import { useSessionTranscript } from '../../api/hooks'
import type { SwarmDetail } from '../../api/contracts/swarm'
import { Markdown } from '../chat/Markdown'
import s from './AgentsPage.module.css'

export default function SavedTeamPanel({ id }: { id: string }) {
  const { data, error } = useQuery({ queryKey: ['agents', 'legacy', id], queryFn: () => api.get<SwarmDetail>(`/agents/legacy/${id}`) })
  const [sid, setSid] = useState('')
  const { data: transcript, error: transcriptError } = useSessionTranscript(sid || undefined)
  const sessions = [...new Set((data?.items ?? []).flatMap(v => v.session_ids))]
  return <section className={s.row}><h3>Saved team history</h3>{error && <p>{error.message}</p>}
    {data && <><p>{data.swarm.goal}</p>{data.swarm.report && <Markdown text={data.swarm.report} />}
      {data.items.map(item => <details className={s.row} key={item.id}><summary>{item.title}<Badge>{item.status}</Badge></summary><p>{item.spec}</p><ul>{item.acceptance.map((text, i) => <li key={i}>{text}</li>)}</ul>
        {item.handoff && <pre>{JSON.stringify(item.handoff, null, 2)}</pre>}{item.review && <pre>{JSON.stringify(item.review, null, 2)}</pre>}
      </details>)}
      <Select aria-label="Historical conversation" value={sid} onValueChange={setSid} placeholder="Inspect a historical transcript" options={sessions.map(value => ({ value, label: value }))} />
      {transcriptError && <p>{transcriptError.message}</p>}{transcript?.messages?.map(message => <article className={s.row} key={message.id}><Badge>{message.role}</Badge><Markdown text={message.content} />
        {message.tool_calls?.map(call => <details key={call.id}><summary>{call.name} · {call.status}</summary><pre>{call.output}</pre></details>)}
      </article>)}
    </>}
  </section>
}
