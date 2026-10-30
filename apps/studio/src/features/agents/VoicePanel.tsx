import { useEffect, useRef, useState } from 'react'
import { Button, Field, Input, Select, Textarea, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useAgents } from '../../api/agents'
import { useModelsOfKind, useSession } from '../../api/hooks'
import { agent, useLive } from '../../api/live'
import type { Job, TranscribeResult } from '../../api/types'
import s from './AgentsPage.module.css'
import LiveCallPanel from './LiveCallPanel'

export default function VoicePanel() {
  const { data } = useAgents()
  const stt = useModelsOfKind('stt').filter(m => m.runtime !== 'openrouter')
  const tts = useModelsOfKind('voice').filter(m => m.runtime !== 'openrouter')
  const [sid, setSid] = useState('')
  const { data: session } = useSession(sid || undefined)
  const [sttId, setSttId] = useState('')
  const [ttsId, setTtsId] = useState('')
  const [voice, setVoice] = useState<string>()
  const preset = voice ?? ((tts.find(model => model.id === (ttsId || tts[0]?.id))?.runtime === 'kokoro') ? 'af_heart' : 'auto')
  const [text, setText] = useState('')
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState(false)
  const [jobId, setJobId] = useState<string>()
  const recorder = useRef<MediaRecorder | undefined>(undefined)
  const stream = useRef<MediaStream | undefined>(undefined)
  const jobs = useLive(s => s.jobs)
  const job = jobs.find(j => j.id === jobId)
  useEffect(() => () => { if (recorder.current?.state === 'recording') { recorder.current.onstop = null; recorder.current.stop() }; stream.current?.getTracks().forEach(t => t.stop()) }, [])
  const err = (e: unknown) => toast.error('Voice operation could not be completed', (e as Error).message)
  const record = async () => {
    if (recording) { recorder.current?.stop(); setRecording(false); return }
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.current = media
      const instance = new MediaRecorder(media)
      recorder.current = instance
      const chunks: Blob[] = []
      instance.ondataavailable = e => { if (e.data.size) chunks.push(e.data) }
      instance.onstop = () => {
        media.getTracks().forEach(t => t.stop())
        setRecording(false); setBusy(true)
        const form = new FormData()
        const type = instance.mimeType
        form.append('file', new Blob(chunks, { type }), type.includes('mp4') ? 'recording.m4a' : 'recording.webm')
        form.append('model_id', sttId || stt[0]?.id || '')
        void api.upload<TranscribeResult>('/voice/transcribe', form).then(r => setText(r.text)).catch(err).finally(() => setBusy(false))
      }
      instance.start(); setRecording(true)
    } catch (e) { err(e) }
  }
  const speak = async () => {
    const reply = [...(session?.messages ?? [])].reverse().find(m => m.role === 'assistant')?.content
    if (!reply) return
    setBusy(true)
    try {
      const job = await api.post<Job>('/voice/tts', { model_id: ttsId || tts[0]?.id, voice_id: preset, text: reply.replace(/[#*_`]/g, '').slice(0, 4000) })
      setJobId(job.id)
    } catch (e) { err(e) } finally { setBusy(false) }
  }
  return <section className={`${s.panel} ${s.narrow}`}><h2>Talk to an agent</h2><p>Choose a conversation and local voice models, then start talking.</p>
    <Field label="Voice conversation"><Select aria-label="Voice conversation" value={sid} onValueChange={setSid} placeholder="Choose a conversation" options={(data?.sessions ?? []).map(c => ({ value: c.id, label: c.title }))} /></Field>
    <div className={s.formGrid}><Field label="Transcription model"><Select aria-label="Transcription model" value={sttId || stt[0]?.id || ''} onValueChange={setSttId} options={stt.map(m => ({ value: m.id, label: m.name }))} placeholder="Install a local transcription model" /></Field>
    <Field label="Speech model"><Select aria-label="Speech model" value={ttsId || tts[0]?.id || ''} onValueChange={value => { setTtsId(value); setVoice(undefined) }} options={tts.map(m => ({ value: m.id, label: m.name }))} placeholder="Install a local speech model" /></Field>
    <Field label="Voice preset or profile"><Input aria-label="Voice preset or profile" value={preset} onChange={e => setVoice(e.target.value)} placeholder="Voice profile or preset ID" /></Field></div>
    <LiveCallPanel key={`${sid}:${sttId || stt[0]?.id}:${ttsId || tts[0]?.id}:${preset}`} sid={sid} sttId={sttId || stt[0]?.id || ''} ttsId={ttsId || tts[0]?.id || ''} voice={preset} />
    <details className={s.row}><summary>Record and review a message</summary>
    <div className={s.actions}><Button disabled={busy || !stt.length} onClick={() => void record()}>{recording ? 'Stop recording' : 'Record message'}</Button></div>
    <Field label="Reviewed voice message"><Textarea aria-label="Reviewed voice message" value={text} onChange={e => setText(e.target.value)} rows={4} /></Field>
    <Button disabled={!sid || !text.trim() || busy} onClick={() => { if (agent.send(sid, text)) setText('') }}>Send message</Button>


    </details>
    <Button variant="secondary" disabled={busy || !sid || !tts.length} onClick={() => void speak()}>Read latest reply</Button>

    {job?.status === 'error' && <p>{job.error}</p>}{job?.status === 'done' && job.result?.outputs.map(o => <audio key={o.id} controls src={o.url} />)}
  </section>
}
