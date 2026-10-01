import { Cloud, HardDrive, Sparkles } from 'lucide-react'
import { Field, Select } from '@studio/ui'
import type { ImageModelProfile } from '../../api/contracts/image'
import { useModelsOfKind } from '../../api/hooks'
import { useImageProfiles } from '../../api/image'
import type { DefaultTask, InstalledModel, ModelKind } from '../../api/types'
import { SettingsSection, type SettingsForm } from './form'
import s from './SettingsPage.module.css'

const AUTO = 'auto'
const CLOUD = new Set(['openrouter', 'tencent-cloud'])

interface Task {
  task: DefaultTask
  label: string
  kind: ModelKind
  hint: string
  accepts?: (p: ImageModelProfile) => boolean
}

const TASKS: Task[] = [
  {
    task: 'image',
    label: 'Image generation',
    kind: 'image',
    hint: "The agent's generate_image, game scene art and the Image page's first pick.",
    accepts: (p) => p.modes.includes('txt2img'),
  },
  {
    task: 'image_edit',
    label: 'Image editing',
    kind: 'image',
    hint: "The agent's edit_image and the Edit page's first pick.",
    accepts: (p) => p.modes.includes('edit') || p.modes.includes('img2img'),
  },
  { task: 'voice', label: 'Speech', kind: 'voice', hint: "The agent's text_to_speech, game narration and the Voice page." },
  { task: 'stt', label: 'Transcription', kind: 'stt', hint: "The agent's transcribe and the Transcribe tab." },
  { task: 'music', label: 'Music', kind: 'music', hint: "The agent's generate_music, game music and the Music page." },
  { task: 'video', label: 'Video', kind: 'video', hint: "The agent's generate_video and the Video page's first pick." },
]

/** Settings → Default models: which model the automatic picks use per task (local by default; cloud when chosen). */
export function DefaultModelsSection({ form }: { form: SettingsForm }) {
  const { data: profiles = [] } = useImageProfiles()
  const defaults = form.values.default_models ?? {}
  const choose = (task: DefaultTask, id: string) => {
    const next = { ...defaults }
    if (id === AUTO) delete next[task]
    else next[task] = id
    form.set('default_models', next)
  }
  return (
    <SettingsSection
      icon={<Sparkles />}
      title="Default models"
      description="What the agent, game mode and each page use unless you pick something else. Automatic picks the best local model; cloud models bill per use."
    >
      <div className={s.defaults}>
        {TASKS.map((t) => (
          <TaskPicker key={t.task} task={t} value={defaults[t.task]} profiles={profiles} onChange={(id) => choose(t.task, id)} />
        ))}
      </div>
    </SettingsSection>
  )
}

function TaskPicker({ task, value, profiles, onChange }: { task: Task; value?: string; profiles: ImageModelProfile[]; onChange: (id: string) => void }) {
  const models = useModelsOfKind(task.kind)
  const profileOf = (m: InstalledModel) => profiles.find((p) => p.model_id === m.id)
  const eligible = task.accepts ? models.filter((m) => {
    const p = profileOf(m)
    return p ? task.accepts!(p) : false
  }) : models
  const describe = (m: InstalledModel) => (CLOUD.has(m.runtime) ? (profileOf(m)?.cost ?? 'Cloud · billed per use') : m.runtime)
  const missing = value && !eligible.some((m) => m.id === value) // uninstalled or unpinned since
  return (
    <Field label={task.label} hint={missing ? 'The chosen model is no longer available — the best local model is used.' : task.hint}>
      {(id) => (
        <Select
          id={id}
          value={value && !missing ? value : AUTO}
          onValueChange={onChange}
          options={[
            { value: AUTO, label: 'Best local (automatic)', icon: <Sparkles /> },
            ...eligible.map((m) => ({
              value: m.id,
              label: m.name,
              description: describe(m),
              icon: CLOUD.has(m.runtime) ? <Cloud /> : <HardDrive />,
            })),
          ]}
        />
      )}
    </Field>
  )
}
