import { ProgressRing } from '@studio/ui'
import s from './Developing.module.css'

/** Placeholder tile while an image renders: the live latent preview when there is one, else a swirl. */
export function Developing({ progress, message, preview }: { progress: number; message?: string; preview?: string }) {
  return (
    <div className={s.tile}>
      {preview ? <img className={s.preview} src={preview} alt="" /> : <div className={s.swirl} />}
      <div className={s.noise} />
      <div className={s.center}>
        <ProgressRing value={progress >= 0 ? progress : null} size={46} stroke={3}>
          {progress >= 0 ? `${Math.round(progress * 100)}` : ''}
        </ProgressRing>
        <span className={s.msg}>{message ?? 'Developing…'}</span>
      </div>
    </div>
  )
}
