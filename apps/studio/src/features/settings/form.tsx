import type { ReactNode } from 'react'
import { Button, Card, Input } from '@studio/ui'
import type { Settings } from '../../api/types'
import s from './form.module.css'

/** What the server returns for a stored write-only secret. */
export const MASK = '•••'

export type SecretKey =
  | 'hf_token'
  | 'openai_api_key'
  | 'openrouter_api_key'
  | 'openrouter_management_key'

/** undefined = unchanged, string = replace, null = clear on save */
export type SecretEdit = string | null | undefined

interface SecretProps {
  stored: boolean
  edit: SecretEdit
  onEdit: (v: SecretEdit) => void
}

/** The settings page's unsaved form, handed to each section / provider card. */
export interface SettingsForm {
  /** Saved settings with unsaved edits applied. */
  values: Settings
  set: <K extends keyof Settings>(key: K, value: Settings[K]) => void
  secret: (key: SecretKey) => SecretProps
}

export function SettingsSection({ icon, title, description, children }: { icon: ReactNode; title: string; description?: string; children: ReactNode }) {
  return (
    <Card padding="none" className={s.section}>
      <div className={s.sectionHead}>
        <span className={s.sectionIcon}>{icon}</span>
        <div>
          <h2 className={s.sectionTitle}>{title}</h2>
          {description && <p className={s.sectionDesc}>{description}</p>}
        </div>
      </div>
      <div className={s.sectionBody}>{children}</div>
    </Card>
  )
}

/** Password-style input for a write-only secret. */
export function SecretInput({ id, stored, edit, onEdit, placeholder }: SecretProps & { id: string; placeholder: string }) {
  const clearing = edit === null
  return (
    <Input
      id={id}
      type="password"
      autoComplete="off"
      value={edit ?? ''}
      disabled={clearing}
      onChange={(e) => onEdit(e.target.value || undefined)}
      placeholder={clearing ? 'Will be removed on save' : stored ? 'Saved — type to replace' : placeholder}
      trailing={
        clearing ? (
          <Button size="sm" variant="ghost" onClick={() => onEdit(undefined)}>
            Undo
          </Button>
        ) : stored && !edit ? (
          <Button size="sm" variant="ghost" onClick={() => onEdit(null)}>
            Remove
          </Button>
        ) : undefined
      }
    />
  )
}
