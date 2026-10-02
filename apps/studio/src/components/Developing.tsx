import { Logo, Materialize, ProgressRing, ScrambleText } from '@studio/ui'
import s from './Developing.module.css'

/**
 * A picture or clip that is still being made. The field of cells fills in as the work progresses (over the live
 * latent preview when there is one), a scan line passes over it, and the logo works inside the progress ring.
 */
export function Developing({ progress, message, preview }: { progress: number; message?: string; preview?: string }) {
  const known = progress >= 0
  return (
    <div className={s.tile}>
      {preview && <img className={s.preview} src={preview} alt="" />}
      <Materialize className={s.field} progress={known ? progress : null} />
      <span className={s.corner} data-at="tl" />
      <span className={s.corner} data-at="tr" />
      <span className={s.corner} data-at="bl" />
      <span className={s.corner} data-at="br" />
      <div className={s.center}>
        <ProgressRing value={known ? progress : null} size={84} stroke={3}>
          <Logo size={52} mode="working" />
        </ProgressRing>
        <span className={s.pct}>{known ? `${Math.round(progress * 100)}%` : ''}</span>
        <ScrambleText className={s.msg} text={message ?? 'Developing…'} duration={420} />
      </div>
    </div>
  )
}
