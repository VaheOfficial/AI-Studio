import { useEffect, useState } from 'react'
import { Cpu, KeyRound, Palette, Settings as SettingsIcon, ShieldCheck } from 'lucide-react'
import { Button, Field, Input, SegmentedControl, Skeleton, Switch } from '@studio/ui'
import { useSettings, useUpdateSettings } from '../../api/hooks'
import type { Settings } from '../../api/types'
import { PageHeader } from '../../components/Page'
import { TASK_PAGES } from '../../components/useModelChoice'
import { useUI } from '../../stores/ui'
import { AssistantSection } from './AssistantSection'
import { ConnectorsSection } from './ConnectorsSection'
import { DefaultModelsSection } from './DefaultModelsSection'
import { StorageSection } from './StorageSection'
import { UpdatesSection } from './UpdatesSection'
import { MASK, SecretInput, SettingsSection, type SecretEdit, type SecretKey, type SettingsForm } from './form'
import { ProvidersSection } from './providers/ProvidersSection'
import s from './SettingsPage.module.css'

const RISKY_TOOLS = [
  { id: 'install_model', label: 'Install models', desc: 'Downloads can be tens of gigabytes.' },
  { id: 'delete_model', label: 'Delete models', desc: 'Removes files from disk.' },
  { id: 'write_file', label: 'Write files', desc: 'Only inside the studio workspace folder.' },
  { id: 'run_command', label: 'Run shell commands', desc: 'PowerShell with a 120s timeout. Leave this off unless you trust the model.' },
  { id: 'run_python', label: 'Run Python code', desc: 'Analysis, charts and documents in a Python session. It can read and write files like any program.' },
]

export default function SettingsPage({ category = 'general', onDirtyChange }: { category?: string; onDirtyChange?: (dirty: boolean) => void }) {
  const { data: settings, isLoading } = useSettings()
  const update = useUpdateSettings()
  const { theme, setTheme } = useUI()
  const [draft, setDraft] = useState<Partial<Settings>>({})
  const [secrets, setSecrets] = useState<Partial<Record<SecretKey, SecretEdit>>>({})


  const form: SettingsForm = {
    values: { ...settings, ...draft } as Settings,
    set: (k, v) => setDraft((d) => ({ ...d, [k]: v })),
    secret: (key) => ({
      name: key,
      stored: settings?.[key] === MASK,
      edit: secrets[key],
      onEdit: (v) => setSecrets((x) => ({ ...x, [key]: v })),
    }),
  }
  // API contract: "" clears a secret
  const secretPatch = Object.fromEntries(
    Object.entries(secrets)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k, v ?? '']),
  )
  const dirty = Object.keys(draft).length > 0 || Object.keys(secretPatch).length > 0
  useEffect(() => { onDirtyChange?.(dirty) }, [dirty, onDirtyChange])
  if (isLoading || !settings) {
    return (
      <div className={s.page}>
        <PageHeader icon={<SettingsIcon />} title={({ general: 'Appearance & updates', models: 'Models & runtime', providers: 'Providers & keys', permissions: 'Permissions', storage: 'Storage' } as Record<string, string>)[category] ?? 'Settings'} />
        <div className={s.content}><Skeleton height={220} radius={16} />
        <Skeleton height={180} radius={16} /></div>
      </div>
    )
  }

  const autoApprove = new Set(form.values.agent_auto_approve)

  const save = () =>
    update.mutate(
      { ...draft, ...secretPatch },
      {
        onSuccess: () => {
          // Pages start from a changed default again (their remembered pick would otherwise hide it)
          if (draft.default_models) {
            const before = settings.default_models ?? {}
            const changed = (Object.keys(TASK_PAGES) as (keyof typeof TASK_PAGES)[]).filter(
              (t) => before[t] !== draft.default_models?.[t],
            )
            useUI.getState().forgetModels(changed.map((t) => TASK_PAGES[t]))
          }
          setDraft({})
          setSecrets({})
        },
      },
    )

  return (
    <div className={s.page}>
      <PageHeader
        icon={<SettingsIcon />}
        title={({ general: 'Appearance & updates', models: 'Models & runtime', providers: 'Providers & keys', permissions: 'Permissions', storage: 'Storage' } as Record<string, string>)[category] ?? 'Settings'}

        actions={
          <Button variant="primary" disabled={!dirty} loading={update.isPending} onClick={save}>
            Save changes
          </Button>
        }
      />

      <div className={s.content}>
      <div hidden={category !== 'permissions'}><AssistantSection form={form} /></div>

      <div hidden={category !== 'providers'}><ConnectorsSection /></div>

      <div hidden={category !== 'providers'}><ProvidersSection form={form} /></div>

      <div hidden={category !== 'models'}><DefaultModelsSection form={form} /></div>

      <div hidden={category !== 'storage'}><StorageSection /></div>

      <div hidden={category !== 'providers'}><SettingsSection icon={<KeyRound />} title="Hugging Face" description="Needed for gated repositories (e.g. FLUX.1-dev) and higher download rate limits.">
        <Field label="Access token">
          {(id) => <SecretInput id={id} {...form.secret('hf_token')} placeholder="hf_…" />}
        </Field>
      </SettingsSection></div>

      <div hidden={category !== 'permissions'}><SettingsSection icon={<ShieldCheck />} title="Agent permissions" description="Tools that run without asking. Everything else always shows an Allow / Deny prompt.">
        <div className={s.switches}>
          {RISKY_TOOLS.map((t) => (
            <Switch
              key={t.id}
              label={t.label}
              description={t.desc}
              checked={autoApprove.has(t.id)}
              onCheckedChange={(on) => {
                const next = new Set(autoApprove)
                if (on) next.add(t.id)
                else next.delete(t.id)
                form.set('agent_auto_approve', [...next])
              }}
            />
          ))}
        </div>
        <Field
          label="Completion check"
          hint="After a turn that used tools, the agent is asked to confirm the work is really done before it stops. It keeps small models from quitting early, and costs one more full-size request each time."
        >
          <SegmentedControl<Settings['agent_completion_check']>
            value={form.values.agent_completion_check}
            onValueChange={(v) => form.set('agent_completion_check', v)}
            segments={[
              { value: 'local', label: 'Local models' },
              { value: 'always', label: 'Always' },
              { value: 'never', label: 'Never' },
            ]}
          />
        </Field>
      </SettingsSection></div>

      <div hidden={category !== 'models'}><SettingsSection icon={<Cpu />} title="Performance" description="How large models are placed when they don't fit entirely in VRAM.">
        <Field label="Memory strategy">
          <SegmentedControl<Settings['offload_policy']>
            value={form.values.offload_policy}
            onValueChange={(v) => form.set('offload_policy', v)}
            segments={[
              { value: 'auto', label: 'Auto' },
              { value: 'gpu', label: 'GPU only' },
              { value: 'cpu-offload', label: 'Model offload' },
              { value: 'sequential-offload', label: 'Sequential offload' },
            ]}
          />
        </Field>
        <Field label="Data folder" hint="Models, environments, outputs and the database live here.">
          <Input value={settings.data_dir} readOnly />
        </Field>
      </SettingsSection></div>

      <div hidden={category !== 'general'}><UpdatesSection /></div>

      <div hidden={category !== 'general'}><SettingsSection icon={<Palette />} title="Appearance">
        <Field label="Theme">
          <SegmentedControl<'dark' | 'light'>
            value={theme}
            onValueChange={setTheme}
            segments={[
              { value: 'dark', label: 'Dark' },
              { value: 'light', label: 'Light' },
            ]}
          />
        </Field>
      </SettingsSection></div>
      </div>
    </div>
  )
}
