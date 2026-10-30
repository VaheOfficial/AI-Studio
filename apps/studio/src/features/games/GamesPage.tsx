import { Link } from 'react-router'
import { Gamepad2, Swords, BookOpen, ArrowUpRight } from 'lucide-react'
import { Badge, Button } from '@studio/ui'
import { useArenaMatches } from '../../api/arena'
import s from './Games.module.css'

export default function GamesPage() {
  const matches = useArenaMatches()
  return <div className={s.hub}>
    <header className={s.hubHeader}><Gamepad2 size={28} /><h1>Games</h1><p>A little chaos between the serious stuff.</p></header>
    <div className={s.gameChoices}>
      <Link to="/games/arena" className={s.arenaChoice}><div className={s.matchup}><Swords size={40} /><span>1 vs 1</span></div><h2>Arena</h2><p>Two models. One challenge. Put their work head to head, or let them argue it out.</p><span className={s.choiceAction}>Enter the arena <ArrowUpRight size={20} /></span></Link>
      <Link to="/games/adventures" className={s.adventureChoice}><BookOpen size={40} /><h2>Adventures</h2><p>Your existing stories, dice rolls and questionable life choices.</p><span className={s.choiceAction}>Play an adventure <ArrowUpRight size={20} /></span></Link>
    </div>
    {matches.isError && <p role="alert">Could not load matches. <Button variant="ghost" onClick={() => void matches.refetch()}>Retry</Button></p>}
    {!!matches.data?.length && <section className={s.history}><h2>Recent matches</h2>{matches.data.slice(0,8).map(m => <Link key={m.id} to={`/games/arena/${m.id}`} className={s.historyRow}><Swords size={18} /><div><strong>{m.left.name} vs {m.right.name}</strong><span>{m.prompt}</span></div><Badge>{m.mode === 'task' ? 'Task' : 'Argument'}</Badge><Badge>{m.status}</Badge><ArrowUpRight size={16} /></Link>)}</section>}
  </div>
}
