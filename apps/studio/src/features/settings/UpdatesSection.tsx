import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Download, ExternalLink, RefreshCw } from 'lucide-react'
import { Badge, Button, Progress, toast } from '@studio/ui'
import { desktop, updatesKey, useUpdates, type UpdateStatus } from '../../lib/desktop'
import { formatBytes } from '../../lib/format'
import { SettingsSection } from './form'
import s from './SettingsPage.module.css'

/** Settings → Updates (desktop app only): the running version, and applying a newer release in place. */
export function UpdatesSection() {
  const qc = useQueryClient()
  const { data: status, isFetching, refetch } = useUpdates()
  const [progress, setProgress] = useState<number | null>(null)
  useEffect(() => desktop?.updates.onProgress(setProgress), [])
  // An app update that could not be put in place reports back here
  useEffect(() => desktop?.updates.onChanged((next) => qc.setQueryData(updatesKey, next)), [qc])
  const install = useMutation({
    mutationFn: async () => (await desktop?.updates.install()) ?? null,
    onSuccess: (next: UpdateStatus | null) => {
      if (next) qc.setQueryData(updatesKey, next)
      if (next?.error) toast.error('The update could not be installed', next.error)
    },
  })
  if (!desktop || !status?.enabled) return null
  const busy = install.isPending || status.state === 'downloading'
  const restarting = status.state === 'ready'

  return (
    <SettingsSection icon={<Download />} title="Updates" description="New versions are downloaded from the project's releases and applied in place; your models, chats and settings stay as they are.">
      <div className={s.updateRow}>
        <div className={s.updateText}>
          <span className={s.updateVersion}>
            Version {status.current}
            {status.available && <Badge tone="accent">{status.latest} available</Badge>}
            {!status.available && !status.needsInstaller && status.latest && <Badge tone="success">Up to date</Badge>}
          </span>
          {status.kind === 'app' && !restarting && (
            <span className={s.updateNote}>
              This version replaces the app itself ({formatBytes(status.size ?? undefined, 0)}): it closes, updates and opens again.
            </span>
          )}
          {status.needsInstaller && (
            <span className={s.updateNote}>
              Version {status.latest} replaces the app itself, and this copy can't do that from where it is installed. Download it once by hand.
            </span>
          )}
          {status.error && <span className={s.updateNote}>{status.error}</span>}
          {restarting && <span className={s.updateNote}>{status.kind === 'app' ? 'Downloaded. Closing to update…' : 'Installed. Restarting…'}</span>}
        </div>
        <div className={s.updateActions}>
          {status.available && (
            <Button variant="primary" iconLeft={<Download />} loading={busy} disabled={restarting} onClick={() => install.mutate()}>
              Install and restart
            </Button>
          )}
          {(status.needsInstaller || status.available) && status.notes && (
            <Button variant="secondary" iconLeft={<ExternalLink />} onClick={() => window.open(status.notes ?? '', '_blank')}>
              {status.needsInstaller ? 'Open the download page' : 'Release notes'}
            </Button>
          )}
          {!status.available && (
            <Button variant="secondary" iconLeft={<RefreshCw />} loading={isFetching} onClick={() => void refetch()}>
              Check now
            </Button>
          )}
        </div>
      </div>
      {busy && <Progress value={progress} size="xs" aria-label="Downloading the update" />}
    </SettingsSection>
  )
}
