import { useEffect, useRef, useState } from 'react'
import { Film, Music2 } from 'lucide-react'
import { SegmentedControl } from '@studio/ui'
import type { DubProject, DubRetimeChunk } from '../../api/contracts/dub'
import { useLanguageName } from '../../api/voice'
import { usePlayback } from './playback'
import s from './PreviewPlayer.module.css'

/** Chunk of a retime map covering source time `t` (the last one past the end). */
function chunkAt(retime: DubRetimeChunk[], t: number): DubRetimeChunk {
  return retime.find((c) => t < c.end) ?? retime[retime.length - 1]
}

/**
 * Source video (or audio) with a track switch: "Original" plays the source; a dubbed track mutes it and plays
 * the dub (over the separated background) in sync. The source stays the clock, so the timeline and segment list
 * keep source times; for a retimed track (smart fit / stretch video) the video slows down chunk by chunk exactly
 * as the export will, and the dub and background follow its mapped position.
 */
export function PreviewPlayer({ project }: { project: DubProject }) {
  const languageName = useLanguageName()
  const media = useRef<HTMLMediaElement | null>(null)
  const dub = useRef<HTMLAudioElement>(null)
  const bed = useRef<HTMLAudioElement>(null)
  const [chosen, setTrack] = useState('original')
  const request = usePlayback((st) => st.request)
  const track = project.tracks[chosen] ? chosen : 'original'
  const current = track === 'original' ? null : project.tracks[track]
  const retimed = (current?.retime.length ?? 0) > 0
  const isVideo = project.source.input_type === 'video'
  const setMedia = (el: HTMLMediaElement | null) => {
    media.current = el
  }

  // Keep dub + bed on the media clock (through the retime map when the track has one).
  useEffect(() => {
    const m = media.current
    if (!m || !current) return
    const retime = current.retime
    const followers = () => [dub.current, bed.current].filter((el): el is HTMLAudioElement => !!el)
    const sync = () => {
      const chunk = retime.length ? chunkAt(retime, m.currentTime) : undefined
      const rate = chunk ? 1 / chunk.ratio : 1
      const at = chunk ? chunk.at + (Math.min(m.currentTime, chunk.end) - chunk.start) * chunk.ratio : m.currentTime
      if (Math.abs(m.playbackRate - rate) > 1e-3) m.playbackRate = rate
      const d = dub.current
      if (d && Math.abs(d.currentTime - at) > 0.15) d.currentTime = at
      const b = bed.current
      if (b) {
        if (Math.abs(b.playbackRate - rate) > 1e-3) b.playbackRate = rate
        if (Math.abs(b.currentTime - m.currentTime) > 0.15) b.currentTime = m.currentTime
      }
    }
    // Rate changes at chunk boundaries need frame accuracy; timeupdate alone fires only ~4×/s.
    let raf = 0
    const follow = () => {
      sync()
      raf = requestAnimationFrame(follow)
    }
    const play = () => {
      sync()
      for (const el of followers()) void el.play()
      if (retime.length) raf = requestAnimationFrame(follow)
    }
    const pause = () => {
      cancelAnimationFrame(raf)
      followers().forEach((el) => el.pause())
    }
    m.addEventListener('play', play)
    m.addEventListener('pause', pause)
    m.addEventListener('seeked', sync)
    m.addEventListener('timeupdate', sync)
    if (!m.paused) play()
    return () => {
      m.removeEventListener('play', play)
      m.removeEventListener('pause', pause)
      m.removeEventListener('seeked', sync)
      m.removeEventListener('timeupdate', sync)
      pause()
      m.playbackRate = 1
    }
  }, [current])

  // Publish the clock for the timeline playhead.
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const el = media.current
      if (el) {
        const st = usePlayback.getState()
        if (st.time !== el.currentTime) st.setTime(el.currentTime)
        if (st.playing === el.paused) st.setPlaying(!el.paused)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  // Seek / play-range requests from the timeline and the segment list.
  useEffect(() => {
    const el = media.current
    if (!request || !el) return
    el.currentTime = request.start
    if (request.end == null) return
    const end = request.end
    void el.play()
    const stop = () => {
      if (el.currentTime >= end) el.pause()
    }
    el.addEventListener('timeupdate', stop)
    return () => el.removeEventListener('timeupdate', stop)
  }, [request])

  const tracks = Object.keys(project.tracks)
  return (
    <div className={s.player}>
      {isVideo ? (
        <video
          ref={setMedia}
          className={s.video}
          src={project.source.media_url}
          poster={project.source.thumb_url}
          controls
          muted={!!current}
          playsInline
        />
      ) : (
        <div className={s.audioOnly}>
          <Music2 />
          <audio ref={setMedia} src={project.source.media_url} controls muted={!!current} />
        </div>
      )}
      {current && <audio ref={dub} src={current.url} preload="auto" />}
      {current && project.separation && <audio ref={bed} src={project.separation.background_url} preload="auto" />}
      {tracks.length > 0 && (
        <SegmentedControl
          size="sm"
          block
          value={track}
          onValueChange={setTrack}
          segments={[
            { value: 'original', label: 'Original', icon: <Film size={13} /> },
            ...tracks.map((t) => ({ value: t, label: languageName(t) })),
          ]}
        />
      )}
      {retimed && <p className={s.note}>{isVideo ? 'The video' : 'Playback'} slows down where the dub needs more time, as in the export.</p>}
    </div>
  )
}
