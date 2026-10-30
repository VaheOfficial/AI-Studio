import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { motion } from 'motion/react'
import { ArrowLeft, Download, Flame, Pause, Play, Send, Square, Swords, Trophy, Zap } from 'lucide-react'
import { Badge, Button, Combobox, Field, Input, Loader, SegmentedControl, Select, Textarea } from '@studio/ui'
import { useArena, useArenaControl, useArenaMatches, useCreateArena, useInterject } from '../../api/arena'
import { useChatModels } from '../../api/hooks'
import type { ArenaContender, ArenaMatch, ArenaSide } from '../../api/contracts/arena'
import { Markdown } from '../chat/Markdown'
import s from './Games.module.css'

const contender = (name: string): ArenaContender => ({ name, model: '', stance: '', persona: '', state: 'idle' })

export default function ArenaPage() {
  const { arenaId } = useParams()
  return arenaId ? <Match key={arenaId} id={arenaId} /> : <Setup />
}

function Setup() {
  const navigate = useNavigate(), create = useCreateArena()
  const { data: models = [] } = useChatModels(), history = useArenaMatches()
  const [mode,setMode] = useState<'argument'|'task'>('argument')
  const [prompt,setPrompt] = useState('')
  const [left,setLeft] = useState(contender('Red corner')), [right,setRight] = useState(contender('Gold corner'))
  const [pacing,setPacing] = useState<'free'|'alternating'>('free')
  const [inference,setInference] = useState<'auto'|'one'|'two'>('auto')
  const [replies,setReplies] = useState('6'), [limit,setLimit] = useState('180')
  const options = models.filter(m => m.available && (mode === 'argument' || m.tools)).map(m => ({ value: m.id, label: m.name, group: m.provider, keywords: m.id, description: m.price ? `$${m.price.output} / million output tokens` : 'Local or configured endpoint' }))
  const ready = !!prompt.trim() && !!left.model && !!right.model && !!left.name.trim() && !!right.name.trim()
  async function start() {
    if (!ready) return
    const result = await create.mutateAsync({ mode, prompt, left, right, pacing, inference, replies: Number(replies), time_limit: Number(limit) })
    navigate(`/games/arena/${result.id}`)
  }
  function corner(value: ArenaContender, set: (v:ArenaContender)=>void, side:ArenaSide) {
    return <section className={s.corner} data-side={side}><div className={s.cornerIcon}><Flame size={27} /></div><Field label="Contender name">{id=><Input id={id} value={value.name} maxLength={60} onChange={e=>set({...value,name:e.target.value})} />}</Field><Field label="Model">{id=><Combobox id={id} value={value.model || undefined} onValueChange={model=>set({...value,model})} options={options} placeholder="Pick your contender" searchPlaceholder="Search models…" emptyText="No available model. Configure one in Models or Settings." />}</Field><Field label={mode==='argument'?'Position or personality':'Style or approach'} hint={mode==='argument'?'Optional. Left defends and right challenges by default.':'Both receive the same task and work independently.'}>{id=><Textarea id={id} value={value.stance} rows={3} maxLength={1200} placeholder={side==='left'?'Confident, precise, viciously funny…':'Skeptical, relentless, allergic to bullshit…'} onChange={e=>set({...value,stance:e.target.value})} />}</Field></section>
  }
  return <div className={s.setup}>
    <Link to="/games" className={s.back}><ArrowLeft size={16} /> Games</Link>
    <header className={s.arenaHeading}><Swords size={28} /><h1>Arena</h1><p>Pick a fight. Or settle it with better work.</p></header>
    <SegmentedControl value={mode} onValueChange={setMode} segments={[{value:'argument',label:'Argument',icon:<Flame size={16}/>},{value:'task',label:'Task competition',icon:<Trophy size={16}/>}]} aria-label="Arena mode" />
    <div className={s.contenders}>{corner(left,setLeft,'left')}<div className={s.versus} aria-hidden="true">vs</div>{corner(right,setRight,'right')}</div>
    <div className={s.challenge}><Field label={mode==='argument'?'What are they fighting about?':'What should they make?'}>{id=><Textarea id={id} rows={3} maxLength={12000} value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder={mode==='argument'?'Tabs vs spaces. Defend your terrible opinion.':'Make the best interactive explanation of how a black hole works.'} />}</Field>
      <div className={s.matchRules}>
        {left.model.startsWith('llamacpp:') && left.model===right.model && <Field label="Generation slots" hint="One loaded model, separate contexts.">{id=><Select id={id} value={inference} onValueChange={setInference} options={[{value:'auto',label:'Auto — try two, fall back to one'},{value:'two',label:'Two — concurrent generation'},{value:'one',label:'One — sequential generation'}]} />}</Field>}
        {mode==='argument' && <><Field label="Pacing">{id=><Select id={id} value={pacing} onValueChange={setPacing} options={[{value:'free',label:'Free fire — both can write'},{value:'alternating',label:'Take turns'}]} />}</Field><Field label="Replies per contender">{id=><Select id={id} value={replies} onValueChange={setReplies} options={['3','6','10','20'].map(v=>({value:v,label:v}))}/>}</Field></>}
        <Field label="Time limit">{id=><Select id={id} value={limit} onValueChange={setLimit} options={[{value:'60',label:'1 minute'},{value:'180',label:'3 minutes'},{value:'600',label:'10 minutes'},{value:'1800',label:'30 minutes'}]}/>}</Field>
        <Button iconLeft={<Swords size={18}/>} disabled={!ready} loading={create.isPending} onClick={()=>void start().catch(()=>{})}>Set up match</Button>
      </div>
      <p className={s.explanation}>{mode==='argument'?'Each contender writes its own competitive persona. Free fire lets them react to rival text while both are writing. Pause, interject or request individual replies whenever you like.':'Both use your existing agent tools in separate chats. Open a contender’s chat for tool results or approvals. Choose the winner yourself.'} {left.model.startsWith('openrouter:')||right.model.startsWith('openrouter:')?'Selected cloud models use your configured account.':''}</p>
    </div>
    {!!history.data?.length && <div className={s.pastMatches}><h2>Previous bouts</h2>{history.data.slice(0,5).map(m=><Link key={m.id} to={`/games/arena/${m.id}`}>{m.left.name} vs {m.right.name}<Badge>{m.status}</Badge></Link>)}</div>}
  </div>
}

function Match({id}:{id:string}) {
  const result = useArena(id), control = useArenaControl(id), interject = useInterject(id)
  const [text,setText] = useState(''), [follow,setFollow] = useState(true)
  const [clock,setClock] = useState(0)
  const match=result.data, bottom=useRef<HTMLDivElement>(null)
  useEffect(()=>{if(follow)bottom.current?.scrollIntoView({block:'nearest'})},[match?.revision,follow])
  useEffect(()=>{const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer)},[])
  if(result.isPending)return <div className={s.loading}><Loader size={100}/></div>
  if(!match)return <div className={s.loading}><p role="alert">{result.error?.message || 'Match not found'}</p><Button onClick={()=>void result.refetch()}>Retry</Button><Link to="/games/arena">Back to arena</Link></div>
  const running=match.status==='running', ended=['done','stopped','error'].includes(match.status)
  const elapsed=match.elapsed_s + (running?Math.max(0,(clock-Date.parse(match.updated_at))/1000):0)
  const seconds=Math.max(0,Math.ceil(match.time_limit-elapsed))
  const act=(action:Parameters<typeof control.mutate>[0])=>control.mutate(action)
  async function send(){if(!text.trim())return;await interject.mutateAsync(text);setText('')}
  function exportMatch(){const url=URL.createObjectURL(new Blob([JSON.stringify(match,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`arena-${id}.json`;a.click();URL.revokeObjectURL(url)}
  return <div className={s.match}>
    <header className={s.matchHeader}><Link to="/games/arena" className={s.back}><ArrowLeft size={16}/> Arena</Link><div className={s.matchTitle}><Badge>{match.mode==='argument'?'Argument':'Task competition'}</Badge><Badge tone={running?'success':'neutral'}>{match.status}</Badge><span className={s.timer}>{Math.floor(seconds/60)}:{String(seconds%60).padStart(2,'0')}</span></div><div className={s.controls}>
      {!ended && <Button variant="secondary" iconLeft={running?<Pause size={16}/>:<Play size={16}/>} loading={control.isPending} onClick={()=>act({action:running?'pause':'start'})}>{running?'Pause':match.status==='ready'?'Start match':'Resume'}</Button>}
      {!ended && match.status!=='ready' && <Button variant="ghost" iconLeft={<Square size={15}/>} onClick={()=>act({action:'stop'})} disabled={control.isPending}>Stop</Button>}
      <Button variant="ghost" iconLeft={<Download size={16}/>} onClick={exportMatch} aria-label="Export match">Export</Button>
    </div></header>
    <div className={s.topic}><h1>{match.prompt}</h1><span>{match.mode==='argument'?(match.pacing==='free'?'Free fire':'Alternating replies'):'Independent agent work'}{match.reason?' · '+match.reason:''}</span></div>
    {match.runtime_note && <div className={s.runtimeNote}><Zap size={14}/><span>{match.runtime_note}{match.context_per_slot ? ` · ${Math.round(match.context_per_slot/1024)}K context per contender` : ''}</span></div>}
    <div className={s.scoreboard}>{(['left','right'] as const).map(side=><Contender key={side} side={side} match={match} onStep={()=>act({action:'step',side})} stepping={control.isPending}/>)}<div className={s.scoreVs} aria-hidden="true">vs</div></div>
    <div className={s.feedToolbar}><span>{match.mode==='argument'?'Live exchange':'Live deliverables'}</span><Button size="sm" variant="ghost" onClick={()=>setFollow(!follow)}>{follow?'Following live':'Follow live'}</Button></div>
    <div className={s.feed}>
      {!match.messages.length && <div className={s.emptyRing}><Swords size={44}/><h2>{match.status==='ready'?'Ready when you are':'Contenders are preparing'}</h2><p>{match.status==='ready'?'Start the match to let both models build their personas and begin.':'Their self-written prompts will appear above.'}</p></div>}
      {match.messages.map(msg=> <motion.article key={msg.id} className={s.bubble} data-side={msg.side} initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} transition={{duration:.2}}><header><strong>{msg.side==='host'?'You':match[msg.side].name}</strong><time>{new Date(msg.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</time>{msg.status==='streaming'?<span className={s.writing}><Zap size={12}/> Writing</span>:msg.status!=='done'?<Badge>{msg.status}</Badge>:null}</header><Markdown text={msg.content || 'Preparing a response…'} live={msg.status==='streaming'}/></motion.article>)}<div ref={bottom}/>
    </div>
    {!ended && <form className={s.interject} onSubmit={e=>{e.preventDefault();void send().catch(()=>{})}}><Input value={text} maxLength={2000} onChange={e=>setText(e.target.value)} placeholder="Throw something into the ring…" aria-label="Host interjection"/><Button type="submit" iconLeft={<Send size={16}/>} disabled={!text.trim()} loading={interject.isPending}>Send</Button><span>{match.mode==='argument'?'Both contenders see this on their next reply.':'Adds a note to this match record.'}</span></form>}
    {!running && match.status!=='ready' && <div className={s.verdict}><Trophy size={22}/><span>{match.winner?match.winner==='tie'?'Draw':`${match[match.winner].name} wins`:'Your call. Who won?'}</span>{(['left','tie','right'] as const).map(winner=><Button key={winner} variant={match.winner===winner?'primary':'secondary'} size="sm" disabled={control.isPending} onClick={()=>act({action:'vote',winner})}>{winner==='tie'?'Draw':match[winner].name}</Button>)}</div>}
  </div>
}

function Contender({match,side,onStep,stepping}:{match:ArenaMatch;side:ArenaSide;onStep:()=>void;stepping:boolean}) {
  const c=match[side], count=match.messages.filter(v=>v.side===side&&v.status==='done').length
  return <section className={s.contenderPanel} data-side={side}><header><div className={s.cornerIcon}><Flame size={23}/></div><div><h2>{c.name}</h2><span>{c.model}</span></div><Badge tone={c.state==='error'?'danger':c.state==='done'?'success':'neutral'}>{c.state}</Badge></header>{match.mode==='argument' && <div className={s.replyCount}>{count} / {match.replies} replies</div>}{c.error && <p className={s.error} role="alert">{c.error}</p>}{c.persona && <details className={s.persona}><summary>Self-written prompt</summary><p>{c.persona}</p></details>}<div className={s.contenderActions}>{c.session_id && <Link to={`/agents/chat/${c.session_id}`}>Open work &amp; tool calls{c.state==='waiting'?' · approval needed':''}</Link>}{match.mode==='argument'&&!['running','done','stopped','error'].includes(match.status)&&count<match.replies && <Button size="sm" variant="ghost" disabled={stepping} onClick={onStep}>One reply</Button>}</div></section>
}

