import { useState, type ReactNode } from 'react'
import { Check, Copy, Eye, EyeOff } from 'lucide-react'
import { Button, Card, IconButton, Input, toast } from '@studio/ui'
import { api } from '../../api/client'
import type { SecretValue, Settings } from '../../api/types'
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
  /** Which secret this is: what the server is asked for when the user wants to see it. */
  name: SecretKey
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

/**
 * Password-style input for a secret. A stored one stays hidden (the page only knows that it is set) until the
 * eye is clicked: the server then hands it over, and it can be read and copied, e.g. into another copy of the studio.
 */
export function SecretInput({ id, name, stored, edit, onEdit, placeholder }: SecretProps & { id: string; placeholder: string }) {
  const clearing = edit === null
  const [shown, setShown] = useState<string>()
  const [copied, setCopied] = useState(false)
  // Only what is stored can be shown: once something is typed or the secret is being removed, there is nothing to reveal
  const revealed = stored && edit === undefined ? shown : undefined
  const reveal = async () => {
    try {
      setShown((await api.get<SecretValue>(`/settings/secrets/${name}`)).value)
    } catch (e) {
      toast.error('Could not show it', (e as Error).message)
    }
  }
  const copy = () => {
    if (revealed === undefined) return
    void navigator.clipboard.writeText(revealed)
    setCopied(true)
    setTimeout(() => setCopied(false), 1400)
  }
  return (
    <Input
      id={id}
      type={revealed !== undefined ? 'text' : 'password'}
      autoComplete="off"
      spellCheck={false}
      value={revealed ?? edit ?? ''}
      readOnly={revealed !== undefined}
      disabled={clearing}
      onChange={(e) => onEdit(e.target.value || undefined)}
      onFocus={(e) => revealed !== undefined && e.currentTarget.select()}
      placeholder={clearing ? 'Will be removed on save' : stored ? 'Saved — type to replace' : placeholder}
      trailing={
        clearing ? (
          <Button size="sm" variant="ghost" onClick={() => onEdit(undefined)}>
            Undo
          </Button>
        ) : stored && !edit ? (
          <>
            {revealed !== undefined && <IconButton size="sm" label={copied ? 'Copied' : 'Copy'} icon={copied ? <Check /> : <Copy />} onClick={copy} />}
            <IconButton
              size="sm"
              label={revealed !== undefined ? 'Hide' : 'Show the saved value'}
              icon={revealed !== undefined ? <EyeOff /> : <Eye />}
              onClick={() => (revealed !== undefined ? setShown(undefined) : void reveal())}
            />
            <Button size="sm" variant="ghost" onClick={() => onEdit(null)}>
              Remove
            </Button>
          </>
        ) : undefined
      }
    />
  )
}
