import { useState } from 'react'
import { FolderInput, FolderSearch, HardDrive } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
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
  const qc = useQueryClient()
  // "Use existing": the folder becomes the models folder as it is (nothing moves) and what it holds is listed
  const adopt = useMutation({
    mutationFn: (body: MoveModelsRequest) => api.post<Job>('/storage/models-dir', body),
    onSuccess: (job) => {
      useLive.getState().upsertJob(job)
      toast.info('Using that folder', 'The models in it are being listed.')
      setTimeout(() => void qc.invalidateQueries({ queryKey: storageKey }), 1500)
    },
    onError: (e: Error) => toast.error('Could not use that folder', e.message),
  })
  const [picking, setPicking] = useState(false)
  const [adopting, setAdopting] = useState(false)
  const [target, setTarget] = useState<string>()

  return (
    <SettingsSection
      icon={<HardDrive />}
      title="Storage"
      description="Model weights can live on another drive: an SSD makes loading big models much faster. Two copies of the studio can share one folder. Ollama and LM Studio keep their own model folders."
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
          <Button variant="ghost" iconLeft={<FolderSearch />} disabled={!data || !!job} loading={adopt.isPending} onClick={() => setAdopting(true)}>
            Use existing…
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
      {adopting && data && (
        <FolderDialog
          title="Use a folder that already has models"
          description="For a folder another copy of the studio keeps its models in, or one you put in place yourself. Nothing is moved: it becomes the models folder as it is, the models in it are listed, and both copies can share it. Models you already installed here stay installed."
          initial=""
          confirmLabel="Use this folder"
          placeholder="D:\AI Models"
          onClose={() => setAdopting(false)}
          onChoose={(path) => adopt.mutate({ path, adopt: true })}
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
