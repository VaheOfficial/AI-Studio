import { cn } from '@studio/ui'
import s from './VoiceOrb.module.css'

function hash(str: string) {
  let h = 0
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0
  return Math.abs(h)
}

/** Deterministic gradient orb per voice — a visual identity without needing avatars. */
export function VoiceOrb({ seed, size = 40, active, className }: { seed: string; size?: number; active?: boolean; className?: string }) {
  const h = hash(seed)
  const a = h % 360
  const b = (a + 40 + (h % 80)) % 360
  return (
    <span
      className={cn(s.orb, active && s.active, className)}
      style={{
        width: size,
        height: size,
        ['--a' as string]: `hsl(${a} 80% 62%)`,
        ['--b' as string]: `hsl(${b} 85% 55%)`,
      }}
      aria-hidden
    />
  )
}
