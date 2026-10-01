import { useNavigate } from 'react-router'
import { Boxes, Cpu, ExternalLink } from 'lucide-react'
import { Badge, Button, Field, SegmentedControl, Select, StatusDot } from '@studio/ui'
import { useLocalBackends } from '../../../api/hub'
import { DefaultBackendPicker } from '../../models/DefaultBackendPicker'
import { BACKEND_NAME, BACKEND_ORDER, backendState } from '../../models/hubMeta'
import { formatTokens } from '../../../lib/format'
import type { KvCacheType } from '../../../api/types'
import type { SettingsForm } from '../form'
import { ProviderCard } from './ProviderCard'
import p from './Providers.module.css'
import s from './LocalModelsCard.module.css'

// What the server accepts (≤ 256K). Speeds: a ~18 GB model (Qwen3.8 27B Q4) on a 24 GB GPU with the 8-bit cache
const LLAMACPP_SIZES: { tokens: number; note?: string }[] = [
  { tokens: 8192 },
  { tokens: 16384 },
  { tokens: 32768 },
  { tokens: 65536 },
  { tokens: 98304, note: 'largest that stays fully on a 24 GB GPU' },
  { tokens: 131072, note: 'part of the model moves to the CPU: slower' },
  { tokens: 196608, note: 'slower' },
  { tokens: 262144, note: 'the most any model here supports; slowest' },
]
const OLLAMA_SIZES = [4096, 8192, 16384, 32768, 65536, 131072, 262144]

/** Local GGUF engines: the default one (LM Studio / llama.cpp / Ollama) and llama.cpp's context window. */
export function LocalModelsCard({ form }: { form: SettingsForm }) {
  const { data: backends = [] } = useLocalBackends()
  const navigate = useNavigate()
  const current = form.values.default_local_backend
  return (
    <ProviderCard
      icon={<Cpu />}
      name="Local models"
      description="GGUF language models run on this PC through LM Studio, the built-in llama.cpp server or Ollama. Free, private, offline."
      status={<Badge size="sm" tone="accent">{BACKEND_NAME[current]}</Badge>}
    >
      <Field label="Default engine" hint="Preselected when you download a GGUF from the model hub; its models lead the chat picker.">
        <DefaultBackendPicker value={current} onValueChange={(v) => form.set('default_local_backend', v)} backends={backends} />
      </Field>
      <Field
        label="llama.cpp context window"
        hint="Tokens of conversation the model sees. What doesn't fit in VRAM next to the model is moved to the CPU, which is slower; the chat summarizes older messages to stay inside the window. Applies the next time a model loads."
      >
        {(id) => (
          <Select
            id={id}
            value={String(form.values.llamacpp_ctx_size)}
            onValueChange={(v) => form.set('llamacpp_ctx_size', Number(v))}
            options={LLAMACPP_SIZES.map((o) => ({
              value: String(o.tokens),
              label: `${formatTokens(o.tokens)} tokens`,
              description: o.note,
            }))}
          />
        )}
      </Field>
      <Field
        label="llama.cpp context memory"
        hint="8-bit halves the memory the context takes, so about twice as much fits on the GPU, with no noticeable quality loss."
      >
        <SegmentedControl<KvCacheType>
          value={form.values.llamacpp_kv_cache}
          onValueChange={(v) => form.set('llamacpp_kv_cache', v)}
          segments={[
            { value: 'q8_0', label: '8-bit' },
            { value: 'f16', label: '16-bit' },
          ]}
        />
      </Field>
      <Field
        label="Ollama context window"
        hint="Tokens the chat model sees per request (capped at what the model supports). The agent trims and summarizes older steps to stay inside it."
      >
        {(id) => (
          <Select
            id={id}
            value={String(form.values.ollama_ctx_size)}
            onValueChange={(v) => form.set('ollama_ctx_size', Number(v))}
            options={OLLAMA_SIZES.map((n) => ({ value: String(n), label: `${formatTokens(n)} tokens` }))}
          />
        )}
      </Field>
      <div className={s.engines}>
        {BACKEND_ORDER.map((id) => {
          const b = backends.find((x) => x.id === id)
          const state = backendState(b)
          return (
            <div key={id} className={s.engine}>
              <StatusDot status={state.dot} />
              <span className={s.engineName}>{BACKEND_NAME[id]}</span>
              <span className={s.engineState}>
                {state.text}
                {b?.version && ` · ${b.version}`}
              </span>
              {b?.install_url && (
                <a className={s.engineLink} href={b.install_url} target="_blank" rel="noreferrer">
                  Get it <ExternalLink size={11} />
                </a>
              )}
            </div>
          )
        })}
      </div>
      <div className={p.actions}>
        <Button size="sm" variant="ghost" iconLeft={<Boxes />} onClick={() => navigate('/models?tab=runtimes')}>
          Manage engines
        </Button>
      </div>
    </ProviderCard>
  )
}
