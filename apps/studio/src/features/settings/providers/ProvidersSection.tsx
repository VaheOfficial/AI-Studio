import { Cloud } from 'lucide-react'
import { Field, Select } from '@studio/ui'
import { useChatModels } from '../../../api/hooks'
import { SettingsSection, type SettingsForm } from '../form'
import { LocalModelsCard } from './LocalModelsCard'
import { OpenAICompatCard } from './OpenAICompatCard'
import { OpenRouterCard } from './OpenRouterCard'
import s from './Providers.module.css'

/** Settings → Providers: one sub-card per model provider. */
export function ProvidersSection({ form }: { form: SettingsForm }) {
  const { data: chatModels = [] } = useChatModels()
  return (
    <SettingsSection icon={<Cloud />} title="Providers" description="Local models run through LM Studio, llama.cpp or Ollama. Connect cloud and self-hosted providers here.">
      <Field label="Default chat model">
        {(id) => (
          <Select
            id={id}
            value={form.values.default_chat_model}
            onValueChange={(v) => form.set('default_chat_model', v)}
            placeholder="First available"
            options={chatModels.map((m) => ({ value: m.id, label: m.name, description: m.provider, disabled: !m.available }))}
          />
        )}
      </Field>
      <div className={s.cards}>
        <LocalModelsCard form={form} />
        <OpenRouterCard form={form} />
        <OpenAICompatCard form={form} />
      </div>
    </SettingsSection>
  )
}
