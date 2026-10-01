import { Server } from 'lucide-react'
import { Badge, Field, Input } from '@studio/ui'
import { SecretInput, type SettingsForm } from '../form'
import { ProviderCard } from './ProviderCard'
import s from './Providers.module.css'

export function OpenAICompatCard({ form }: { form: SettingsForm }) {
  const url = form.values.openai_base_url ?? ''
  return (
    <ProviderCard
      icon={<Server />}
      name="OpenAI-compatible endpoint"
      description="vLLM, SGLang or any hosted /v1 API — e.g. for MiMo-V2.6-Pro on a GPU box."
      status={url && <Badge size="sm" tone="success" dot>Configured</Badge>}
    >
      <div className={s.row2}>
        <Field label="Base URL">
          {(id) => <Input id={id} value={url} onChange={(e) => form.set('openai_base_url', e.target.value)} placeholder="http://my-gpu-box:8000/v1" />}
        </Field>
        <Field label="API key">{(id) => <SecretInput id={id} {...form.secret('openai_api_key')} placeholder="Optional" />}</Field>
      </div>
    </ProviderCard>
  )
}
