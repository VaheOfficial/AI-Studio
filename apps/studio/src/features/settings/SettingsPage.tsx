import { useState } from 'react'
import { Cpu, KeyRound, Palette, Settings as SettingsIcon, ShieldCheck } from 'lucide-react'
import { Button, Field, Input, SegmentedControl, Skeleton, Switch } from '@studio/ui'
import { useSettings, useUpdateSettings } from '../../api/hooks'
import type { Settings } from '../../api/types'
import { PageBody, PageHeader } from '../../components/Page'
import { TASK_PAGES } from '../../components/useModelChoice'
import { useUI } from '../../stores/ui'
import { AssistantSection } from './AssistantSection'
import { ConnectorsSection } from './ConnectorsSection'
import { DefaultModelsSection } from './DefaultModelsSection'
import { StorageSection } from './StorageSection'
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

export default function SettingsPage() {
  const { data: settings, isLoading } = useSettings()
  const update = useUpdateSettings()
  const { theme, setTheme } = useUI()
  const [draft, setDraft] = useState<Partial<Settings>>({})
  const [secrets, setSecrets] = useState<Partial<Record<SecretKey, SecretEdit>>>({})

  if (isLoading || !settings) {
    return (
      <PageBody>
        <PageHeader icon={<SettingsIcon />} title="Settings" />
        <Skeleton height={220} radius={16} />
        <Skeleton height={180} radius={16} />
      </PageBody>
    )
  }

  const form: SettingsForm = {
    values: { ...settings, ...draft },
    set: (k, v) => setDraft((d) => ({ ...d, [k]: v })),
    secret: (key) => ({
      stored: settings[key] === MASK,
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
    <PageBody>
      <PageHeader
        icon={<SettingsIcon />}
        title="Settings"
        subtitle="Keys are stored locally in the studio database and never leave this machine except to the provider you configure."
        actions={
          <Button variant="primary" disabled={!dirty} loading={update.isPending} onClick={save}>
            Save changes
          </Button>
        }
      />

      <AssistantSection form={form} />

      <ConnectorsSection />

      <ProvidersSection form={form} />

      <DefaultModelsSection form={form} />

      <StorageSection />

      <SettingsSection icon={<KeyRound />} title="Hugging Face" description="Needed for gated repositories (e.g. FLUX.1-dev) and higher download rate limits.">
        <Field label="Access token">
          {(id) => <SecretInput id={id} {...form.secret('hf_token')} placeholder="hf_…" />}
        </Field>
      </SettingsSection>

      <SettingsSection icon={<ShieldCheck />} title="Agent permissions" description="Tools that run without asking. Everything else always shows an Allow / Deny prompt.">
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
      </SettingsSection>

      <SettingsSection icon={<Cpu />} title="Performance" description="How large models are placed when they don't fit entirely in VRAM.">
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
      </SettingsSection>

      <SettingsSection icon={<Palette />} title="Appearance">
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
      </SettingsSection>
    </PageBody>
  )
}
