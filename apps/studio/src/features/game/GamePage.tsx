import { useParams } from 'react-router'
import { GameView } from './GameView'
import { NewGame } from './NewGame'

/** Game mode: the open adventure, or a new one. Saved adventures are listed under Game in the sidebar. */
export default function GamePage() {
  const { gameId } = useParams()
  return gameId ? <GameView key={gameId} id={gameId} /> : <NewGame />
}
