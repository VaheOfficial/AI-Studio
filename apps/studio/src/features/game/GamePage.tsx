import { useState } from 'react'
import { NavLink, useMatch, useNavigate, useParams } from 'react-router'
import { MoreHorizontal, Plus, Skull, Swords, Trash2, Trophy } from 'lucide-react'
import { Badge, Button, ConfirmDialog, EmptyState, IconButton, Menu, Skeleton, cn } from '@studio/ui'
import type { GameSummary } from '../../api/contracts/game'
import { useDeleteGame, useGames } from '../../api/game'
import { GameView } from './GameView'
import { NewGame } from './NewGame'
import s from './GamePage.module.css'

/** Game mode: saved adventures on the left, the open game (or a new one) beside them. */
export default function GamePage() {
  const { gameId } = useParams()
  return (
    <div className={s.page}>
      <GameList />
      {gameId ? <GameView key={gameId} id={gameId} /> : <NewGame />}
    </div>
  )
}

function GameList() {
  const { data, isLoading } = useGames()
  const navigate = useNavigate()
  return (
    <aside className={s.list}>
      <div className={s.listHead}>
        <span>Adventures</span>
        <IconButton size="sm" label="New game" icon={<Plus />} onClick={() => navigate('/game')} />
      </div>
      {isLoading ? (
        [0, 1, 2].map((i) => <Skeleton key={i} height={44} />)
      ) : !data?.length ? (
        <EmptyState icon={<Swords />} tint="var(--hue-game)" title="No adventures yet" description="Start one on the right." />
      ) : (
        data.map((g) => <GameRow key={g.id} game={g} />)
      )}
      <Button variant="secondary" size="sm" iconLeft={<Plus />} className={s.newButton} onClick={() => navigate('/game')}>
        New game
      </Button>
    </aside>
  )
}

function GameRow({ game }: { game: GameSummary }) {
  const navigate = useNavigate()
  const active = !!useMatch(`/game/${game.id}`)
  const remove = useDeleteGame()
  const [confirming, setConfirming] = useState(false)
  return (
    <div className={cn(s.row, active && s.rowActive)}>
      <NavLink to={`/game/${game.id}`} className={s.rowLink}>
        <span className={s.rowTitle}>{game.title}</span>
        <span className={s.rowMeta}>
          Lv {game.level} {game.role} · {game.turns} {game.turns === 1 ? 'turn' : 'turns'}
          {game.status === 'dead' && (
            <Badge size="sm" tone="danger" icon={<Skull size={10} />}>
              Fallen
            </Badge>
          )}
          {game.status === 'won' && (
            <Badge size="sm" tone="success" icon={<Trophy size={10} />}>
              Won
            </Badge>
          )}
        </span>
      </NavLink>
      <span className={s.rowMenu}>
        <Menu
          trigger={<IconButton size="sm" label="Game actions" icon={<MoreHorizontal />} />}
          items={[{ label: 'Delete', icon: <Trash2 size={14} />, danger: true, onSelect: () => setConfirming(true) }]}
        />
      </span>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Delete this adventure?"
        description={`“${game.title}” and its whole story are deleted.`}
        confirmLabel="Delete"
        tone="danger"
        onConfirm={async () => {
          await remove.mutateAsync(game.id)
          if (active) navigate('/game')
        }}
      />
    </div>
  )
}
