import { useEffect, useRef } from 'react'
import { ImagePlus, Music, Pause, Play, Volume2 } from 'lucide-react'
import { AudioPlayer, Button, IconButton, Spinner, Tooltip } from '@studio/ui'
import type { Game, GameTurn } from '../../api/contracts/game'
import { mediaKey, useGameMedia, useMakeMedia } from '../../api/game'
import { useGamePrefs } from './prefs'
import s from './GameView.module.css'

/** A turn's picture and narration, with the buttons that make them. */
export function TurnMedia({ gameId, turn, autoPlay }: { gameId: string; turn: GameTurn; autoPlay: boolean }) {
  const make = useMakeMedia(gameId)
  const drawing = useGameMedia((st) => !!st.busy[mediaKey(gameId, turn.id, 'image')])
  const reading = useGameMedia((st) => !!st.busy[mediaKey(gameId, turn.id, 'audio')])
  return (
    <>
      {turn.image && <img className={s.scene} src={turn.image} alt={turn.scene || 'Scene'} loading="lazy" />}
      {turn.audio && <AudioPlayer src={turn.audio} compact height={28} color="var(--hue-game)" autoPlay={autoPlay} className={s.narrationAudio} />}
      <div className={s.turnTools}>
        {!turn.image && (
          <Tooltip content={turn.scene ? `Draw: ${turn.scene}` : 'Draw this moment with your best image model'}>
            <Button size="sm" variant="ghost" iconLeft={drawing ? <Spinner size={13} /> : <ImagePlus />} disabled={drawing} onClick={() => make.mutate({ kind: 'image', turnId: turn.id })}>
              {drawing ? 'Illustrating…' : 'Illustrate'}
            </Button>
          </Tooltip>
        )}
        {!turn.audio && (
          <Button size="sm" variant="ghost" iconLeft={reading ? <Spinner size={13} /> : <Volume2 />} disabled={reading} onClick={() => make.mutate({ kind: 'audio', turnId: turn.id })}>
            {reading ? 'Recording…' : 'Read aloud'}
          </Button>
        )}
      </div>
    </>
  )
}

/** The current location's music: compose it once, then it loops while you are there. */
export function MusicControl({ game }: { game: Game }) {
  const location = game.state.location.name
  const url = game.soundtrack[location]
  const on = useGamePrefs((st) => st.music)
  const setOn = useGamePrefs((st) => st.setMusic)
  const make = useMakeMedia(game.id)
  const composing = useGameMedia((st) => !!st.busy[mediaKey(game.id, location, 'music')])
  const audio = useRef<HTMLAudioElement>(null)
  useEffect(() => {
    const el = audio.current
    if (!el) return
    el.volume = 0.35
    if (on) void el.play().catch(() => undefined) // blocked until the page has had a click; the toggle retries
    else el.pause()
  }, [on, url])
  if (!url) {
    return (
      <Tooltip content={`Compose a looping track for ${location} (ACE-Step, about a minute)`}>
        <Button size="sm" variant="ghost" iconLeft={composing ? <Spinner size={13} /> : <Music />} disabled={composing} onClick={() => make.mutate({ kind: 'music', location })}>
          {composing ? 'Composing…' : 'Compose music'}
        </Button>
      </Tooltip>
    )
  }
  return (
    <>
      <audio ref={audio} src={url} loop preload="auto" />
      <IconButton label={on ? `Pause the music of ${location}` : `Play the music of ${location}`} icon={on ? <Pause /> : <Play />} active={on} onClick={() => setOn(!on)} />
    </>
  )
}
