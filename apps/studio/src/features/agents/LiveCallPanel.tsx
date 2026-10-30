import { useEffect, useRef, useState } from 'react'
import { Badge, Button, Switch } from '@studio/ui'
import { api } from '../../api/client'
import { agent, useLive } from '../../api/live'
import { useSession } from '../../api/hooks'
import { useDictation } from '../voice/useDictation'
import type { Job } from '../../api/types'
import s from './AgentsPage.module.css'
import { ToolCallCard } from '../chat/ToolCallCard'

export default function LiveCallPanel({ sid, sttId, ttsId, voice }: { sid: string; sttId: string; ttsId: string; voice: string }) {
  const [active, setActive] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [bargeIn, setBargeIn] = useState(false)
  const [pending, setPending] = useState<string[]>([])
  const [speechJob, setSpeechJob] = useState<string>()
  const [error, setError] = useState('')
  const turn = useLive(state => state.turns[sid])
  const jobs = useLive(state => state.jobs)
  const { data: session } = useSession(sid || undefined)
  const playback = useRef<HTMLAudioElement | null>(null)
  const seen = useRef(0)
  const spoken = useRef(new Set<string>())
  const ticket = useRef(0)
  const currentJob = useRef<string | undefined>(undefined)
  const interrupt = () => { if (currentJob.current) void api.post(`/jobs/${currentJob.current}/cancel`).catch(() => {}); currentJob.current = undefined; ticket.current++; playback.current?.pause(); playback.current = null; setSpeaking(false); setSpeechJob(undefined) }
  const dictation = useDictation(sttId || undefined, undefined, { paused: speaking && !bargeIn, onSpeech: () => { if (active && bargeIn && speaking) interrupt() } })
  const cancelDictation = dictation.cancel
  const calls = turn?.message.tool_calls ?? []
  const question = calls.find(call => call.status === 'awaiting_input' && call.display?.kind === 'question')
  const questionId = question?.id
  const end = () => { setActive(false); cancelDictation(); interrupt(); setPending([]) }
  useEffect(() => () => { ticket.current++; playback.current?.pause(); if (currentJob.current) void api.post(`/jobs/${currentJob.current}/cancel`).catch(() => {}) }, [])
  useEffect(() => {
    if (!active) return
    const fresh = dictation.finals.slice(seen.current).map(text => text.trim()).filter(Boolean)
    seen.current = dictation.finals.length
    if (!fresh.length) return
    if (questionId) { agent.answer(sid, questionId, fresh.join(' ')); return }
    if (pending.length + fresh.length > 20) { setError('Speech queue is full. This utterance was not sent: ' + fresh.join(' ')); cancelDictation(); setActive(false); return }
    setPending(queue => [...queue, ...fresh])
  }, [active, dictation.finals, questionId, sid, pending, cancelDictation])
  useEffect(() => {
    if (!active || turn?.streaming || !pending.length) return
    // eslint-disable-next-line react/set-state-in-effect -- Clear queued utterances after the WebSocket accepts them.
    if (agent.send(sid, pending.join(' '))) setPending([])
  }, [active, turn?.streaming, pending, sid])
  useEffect(() => {
    if (!active || !ttsId || turn?.streaming || speaking || speechJob) return
    const reply = [...(session?.messages ?? [])].reverse().find(message => message.role === 'assistant' && message.content.trim())
    if (!reply || spoken.current.has(reply.id)) return
    spoken.current.add(reply.id)
    const current = ticket.current
    setSpeaking(true)
    void api.post<Job>('/voice/tts', { model_id: ttsId, voice_id: voice, text: reply.content.replace(/[#*_`]/g, '').slice(0, 4000) })
      .then(job => { if (current !== ticket.current) { void api.post(`/jobs/${job.id}/cancel`).catch(() => {}); return }; currentJob.current = job.id; useLive.setState(state => ({ jobs: state.jobs.some(item => item.id === job.id) ? state.jobs : [job, ...state.jobs] })); setSpeechJob(job.id) })
      .catch(reason => { if (current === ticket.current) { setError((reason as Error).message); setSpeaking(false) } })
  }, [active, session?.messages, turn?.streaming, speaking, speechJob, ttsId, voice])
  useEffect(() => {
    const job = jobs.find(item => item.id === speechJob)
    if (!job || !['done', 'error', 'cancelled'].includes(job.status)) return
    // eslint-disable-next-line react/set-state-in-effect -- Consume the server job event before starting audio playback.
    setSpeechJob(undefined); currentJob.current = undefined
    if (job.status !== 'done' || !job.result?.outputs[0]) { setError(job.error ?? 'Speech did not produce audio'); setSpeaking(false); return }
    const audio = new Audio(job.result.outputs[0].url)
    playback.current = audio
    audio.onended = () => { playback.current = null; setSpeaking(false) }
    audio.onerror = () => { setError('Speech playback failed'); playback.current = null; setSpeaking(false) }
    void audio.play().catch(reason => { setError((reason as Error).message); setSpeaking(false) })
  }, [jobs, speechJob])
  useEffect(() => {
    if (!speechJob) return
    const timeout = setTimeout(() => { if (currentJob.current !== speechJob) return; void api.post(`/jobs/${speechJob}/cancel`).catch(() => {}); currentJob.current = undefined; setSpeechJob(undefined); setSpeaking(false); setError('Speech synthesis timed out') }, 180000)
    return () => clearTimeout(timeout)
  }, [speechJob])
  return <article className={s.row}><h3>Continuous local conversation</h3>
    <p>Finished utterances become messages or answers to the agent’s question. Approvals still require a button.</p>
    <Switch label="Interrupt playback when speech is recognized" checked={bargeIn} onCheckedChange={setBargeIn} />
    <p>{bargeIn ? 'The microphone stays active during playback with browser echo cancellation. Headphones improve reliability. Interruption begins when local transcription recognizes speech.' : 'Speech playback mutes transcription to prevent echoes. Use Interrupt speech to take your turn.'}</p>
    <Badge>{active ? speaking ? 'Speaking' : dictation.stage : 'Call ended'}</Badge>
    <div className={s.actions}><Button disabled={!sid || !session || !sttId || active} onClick={() => { spoken.current = new Set((session?.messages ?? []).map(message => message.id)); seen.current = 0; setError(''); setActive(true); void dictation.start() }}>Start call</Button>
      <Button variant="secondary" disabled={!active} onClick={end}>End call</Button>
      <Button variant="secondary" disabled={!speaking} onClick={interrupt}>Interrupt speech</Button>
      <Button variant="ghost" disabled={!active || !turn?.streaming} onClick={() => agent.stop(sid)}>Stop agent</Button></div>
    {(dictation.error || error) && <p role="alert">{dictation.error || error}</p>}
    {dictation.partial && <p>{dictation.partial}</p>}{pending.length > 0 && <p>Waiting for the agent: {pending.join(' ')}</p>}
    {question?.display?.kind === 'question' && <p>{question.display.question}</p>}
    {calls.filter(call => call.status === 'pending_approval').map(call => <ToolCallCard key={call.id} call={call} onApprove={(id, ok) => agent.approve(sid, id, ok)} />)}
  </article>
}
