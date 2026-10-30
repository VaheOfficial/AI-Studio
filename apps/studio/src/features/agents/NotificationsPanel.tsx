import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { Badge, Button, Field, Input, Switch, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useAgentMutation } from '../../api/agents'
import type { AgentNotification, NotificationSettings } from '../../api/contracts/agents'
import s from './AgentsPage.module.css'

export default function NotificationsPanel() {
  const { data } = useQuery({ queryKey:['agents','notifications'],queryFn:() => api.get<AgentNotification[]>('/agents/notifications') })
  const { data: settings } = useQuery({ queryKey:['agents','notification-settings'],queryFn:() => api.get<NotificationSettings>('/agents/notification-settings') })
  const [draft, setDraft] = useState<NotificationSettings>()
  const value = draft ?? settings
  const save = useAgentMutation((body: NotificationSettings) => api.put<NotificationSettings>('/agents/notification-settings',body))
  const read = useAgentMutation((id: string) => api.patch(`/agents/notifications/${id}`,{}))
  return <section className={s.row}><h3>Notifications</h3><p>Approvals, questions, errors and completed missions remain in this inbox.</p>
    {value && <details className={s.technical}><summary>Notification preferences</summary><div className={s.editor}><Field label="Independent host desktop notifications" hint="Shows a generic OS notification when no client is connected."><Switch checked={value.native_desktop} onCheckedChange={enabled => setDraft({ ...value,native_desktop:enabled })} /></Field>
      <Field label="Background browser push" hint="Opt-in delivery through your browser's push service. Requires HTTPS and a notification-scoped device grant."><Switch checked={value.web_push} onCheckedChange={enabled => setDraft({ ...value,web_push:enabled })} /></Field>
      <Input aria-label="Push operator contact" value={value.contact} onChange={e => setDraft({ ...value,contact:e.target.value })} placeholder="mailto:you@example.com" />
      <Button disabled={save.isPending} onClick={() => save.mutate(value,{onSuccess:() => {setDraft(undefined);toast.success('Notification preferences saved')},onError:e => toast.error('Preferences could not be saved',e.message)})}>Save preferences</Button>
    </div></details>}
    {data?.length === 0 && <p className={s.hint}>You’re all caught up. Agent updates will appear here.</p>}
    {data?.map(note => <article key={note.id} className={s.row}><div className={s.actions}><Badge>{note.kind}</Badge><strong>{note.title}</strong><Link to={`/agents/chat/${note.session_id}`}>Open conversation</Link>{!note.read && <Button variant="ghost" size="sm" onClick={() => read.mutate(note.id)}>Mark read</Button>}</div><p>{note.body}</p><small>{note.created_at}</small></article>)}
  </section>
}
