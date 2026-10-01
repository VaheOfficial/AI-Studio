import { useState } from 'react'
import { FolderInput, HardDrive } from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Button, ConfirmDialog, Field, Input, Progress, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useLive } from '../../api/live'
import type { Job, MoveModelsRequest, StorageInfo } from '../../api/types'
import { FolderDialog } from '../../components/FolderDialog'
import { formatBytes } from '../../lib/format'
import { SettingsSection } from './form'
import s from './SettingsPage.module.css'

const storageKey = ['storage'] as const

/** Settings → Storage: where model weights live, and moving them (e.g. to an SSD for faster loads). */
export function StorageSection() {
  const { data } = useQuery({ queryKey: storageKey, queryFn: () => api.get<StorageInfo>('/storage') })
  const move = useMutation({
    mutationFn: (body: MoveModelsRequest) => api.post<Job>('/storage/models-dir', body),
    onSuccess: (job) => useLive.getState().upsertJob(job),
    onError: (e: Error) => toast.error('Could not move the models', e.message),
  })
  const job = useLive((st) => st.jobs.find((j) => j.kind === 'storage' && (j.status === 'running' || j.status === 'queued')))
  const [picking, setPicking] = useState(false)
  const [target, setTarget] = useState<string>()

  return (
    <SettingsSection
      icon={<HardDrive />}
      title="Storage"
      description="Model weights can live on another drive — an SSD makes loading big models much faster. Ollama and LM Studio keep their own model folders."
    >
      <Field
        label="Models folder"
        hint={data ? `${formatBytes(data.size_bytes)} of models · ${formatBytes(data.free_bytes)} free on this drive` : undefined}
      >
        <div className={s.storageRow}>
          <Input value={data?.models_dir ?? ''} readOnly />
          <Button variant="secondary" iconLeft={<FolderInput />} disabled={!data || !!job} onClick={() => setPicking(true)}>
            Move…
          </Button>
        </div>
      </Field>
      {job && (
        <div className={s.storageJob}>
          <Progress value={job.progress} size="xs" />
          <span>{job.message ?? 'Moving…'}</span>
        </div>
      )}
      {picking && data && (
        <FolderDialog
          title="Move models to…"
          description="Pick an empty or new folder, e.g. on an SSD. Models are unloaded first and generation pauses while the files move."
          initial=""
          confirmLabel="Move here"
          placeholder="D:\AI Models"
          onClose={() => setPicking(false)}
          onChoose={(path) => setTarget(path)}
        />
      )}
      <ConfirmDialog
        open={!!target}
        onOpenChange={(open) => !open && setTarget(undefined)}
        title={`Move ${data ? formatBytes(data.size_bytes) : 'all models'} to ${target}?`}
        description="On the same drive this is instant. To another drive every file is copied (this can take a while), then the old copy is removed. You can keep using chat meanwhile; loading models waits until it's done."
        confirmLabel="Move models"
        onConfirm={() => {
          if (target) move.mutate({ path: target })
          setTarget(undefined)
        }}
      />
    </SettingsSection>
  )
}
