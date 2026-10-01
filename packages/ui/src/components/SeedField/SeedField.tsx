import type { ReactNode } from 'react'
import { Lock, LockOpen } from 'lucide-react'
import { Field } from '../Field/Field'
import { IconButton } from '../IconButton/IconButton'
import { Input } from '../Input/Input'
import s from './SeedField.module.css'

export interface SeedFieldProps {
  /** A fixed seed, or null for a new random seed on every run. */
  value: number | null
  onChange: (value: number | null) => void
  /** The seed the last run used (shown while random, so a good result can be kept). */
  lastUsed?: number
  label?: string
  hint?: ReactNode
}

const MAX_SEED = 2 ** 31 - 1

/** A seed that is random on every run unless locked: typing a number or keeping the last one locks it. */
export function SeedField({ value, onChange, lastUsed, label = 'Seed', hint }: SeedFieldProps) {
  const locked = value !== null
  return (
    <Field
      label={label}
      hint={
        !locked && lastUsed != null ? (
          <span className={s.last}>
            Last run: {lastUsed}
            <button className={s.keep} onClick={() => onChange(lastUsed)}>
              Keep it
            </button>
          </span>
        ) : (
          (hint ?? (locked ? 'Locked: every run uses this seed.' : 'Random on every run. Type a number to lock one.'))
        )
      }
    >
      {(id) => (
        <Input
          id={id}
          inputMode="numeric"
          placeholder="Random every time"
          value={locked ? String(value) : ''}
          onChange={(e) => {
            const digits = e.target.value.replace(/\D/g, '')
            onChange(digits ? Math.min(Number(digits), MAX_SEED) : null)
          }}
          trailing={
            <IconButton
              size="sm"
              label={locked ? 'Unlock: random on every run' : lastUsed != null ? 'Lock the last seed' : 'Random on every run'}
              icon={locked ? <Lock /> : <LockOpen />}
              active={locked}
              disabled={!locked && lastUsed == null}
              onClick={() => onChange(locked ? null : (lastUsed ?? null))}
            />
          }
        />
      )}
    </Field>
  )
}

/** The seed for a run: the locked one, else a fresh random one. */
export function resolveSeed(value: number | null): number {
  return value ?? Math.floor(Math.random() * MAX_SEED)
}
