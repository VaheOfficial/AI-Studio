import { useState } from 'react'
import { useNavigate } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowUpRight, Boxes, FolderOpen, MoreHorizontal, Play, Power, Trash2 } from 'lucide-react'
import { Badge, Button, ConfirmDialog, EmptyState, IconButton, Menu, Skeleton, StatusDot, Tooltip } from '@studio/ui'
import { useDeleteModel, useModelPower } from '../../api/hooks'
import { useLive } from '../../api/live'
import type { InstalledModel, ModelKind } from '../../api/types'
import { formatBytes, timeAgo } from '../../lib/format'
import { KINDS, KIND_ORDER } from '../../lib/kinds'
import { FORMAT_LABEL } from './hubMeta'
import s from './InstalledList.module.css'

export function InstalledList({ kind, onBrowse }: { kind: ModelKind | 'all'; onBrowse: () => void }) {
  const models = useLive((st) => st.models)
  const synced = useLive((st) => st.synced)
  const [toDelete, setToDelete] = useState<InstalledModel | null>(null)
  const del = useDeleteModel()

  if (!synced) {
    return (
      <div className={s.list}>
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} height={62} radius={12} />
        ))}
      </div>
    )
  }

  const visible = models.filter((m) => kind === 'all' || m.kind === kind)
  if (visible.length === 0) {
    return (
      <EmptyState
        icon={<Boxes />}
        title={kind === 'all' ? 'Your library is empty' : `No ${KINDS[kind].plural.toLowerCase()} yet`}
        description="Find any model on Hugging Face, LM Studio's catalog or the Ollama library. Downloads resume if interrupted, and runtimes install themselves the first time they're needed."
        action={
          <Button variant="primary" onClick={onBrowse}>
            Discover models
          </Button>
        }
      />
    )
  }

  const groups = KIND_ORDER.map((k) => ({ kind: k, items: visible.filter((m) => m.kind === k) })).filter((g) => g.items.length)

  return (
    <>
      <div className={s.groups}>
        {groups.map((g) => (
          <section key={g.kind} className={s.group}>
            <h3 className={s.groupTitle} style={{ ['--hue' as string]: KINDS[g.kind].hue }}>
              {KINDS[g.kind].icon}
              {KINDS[g.kind].plural}
              <span className={s.groupCount}>{g.items.length}</span>
            </h3>
            <div className={s.list}>
              <AnimatePresence initial={false}>
                {g.items.map((m) => (
                  <ModelRow key={m.id} model={m} onDelete={() => setToDelete(m)} />
                ))}
              </AnimatePresence>
            </div>
          </section>
        ))}
      </div>
      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        tone="danger"
        title={toDelete?.runtime === 'openrouter' ? `Unpin ${toDelete.name}?` : `Delete ${toDelete?.name}?`}
        description={
          toDelete?.runtime === 'openrouter'
            ? 'It leaves your model lists; pin it again any time from Models → Cloud.'
            : `This removes ${formatBytes(toDelete?.size_bytes)} of model files from disk. You can re-download it from the catalog later.`
        }
        confirmLabel={toDelete?.runtime === 'openrouter' ? 'Unpin' : 'Delete'}
        onConfirm={() => del.mutateAsync(toDelete!.id)}
      />
    </>
  )
}

function ModelRow({ model, onDelete }: { model: InstalledModel; onDelete: () => void }) {
  const meta = KINDS[model.kind]
  const runtimeName = useLive((st) => st.runtimes.find((r) => r.id === model.runtime)?.name ?? model.runtime)
  const power = useModelPower()
  const navigate = useNavigate()
  const loaded = model.status === 'loaded'
  const busy = model.status === 'loading' || power.isPending
  // Pinned OpenRouter models run in the cloud: nothing on disk, nothing to load
  const cloud = model.runtime === 'openrouter'
  // Ollama and remote models load on demand; explicit load/unload only matters for worker runtimes
  const managedMemory = model.runtime !== 'remote' && !cloud

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: -16, height: 0, marginBottom: 0 }}
      className={s.row}
      style={{ ['--hue' as string]: meta.hue }}
      data-loaded={loaded || undefined}
    >
      <span className={s.icon}>{meta.icon}</span>
      <div className={s.info}>
        <div className={s.nameRow}>
          <span className={s.name}>{model.name}</span>
          <Badge size="sm">{runtimeName}</Badge>
          {model.format && model.format !== 'ollama' && (
            <Badge size="sm" tone={model.format === 'gguf' ? 'accent' : 'neutral'}>
              {FORMAT_LABEL[model.format]}
              {model.quant && ` · ${model.quant}`}
            </Badge>
          )}
        </div>
        <span className={s.meta}>
          {cloud ? `Cloud · pinned ${timeAgo(model.installed_at)}` : `${formatBytes(model.size_bytes)} · installed ${timeAgo(model.installed_at)}`}
          {model.source_repo && !cloud && <span className={s.source}> · {model.source_repo}</span>}
        </span>
      </div>
      <div className={s.status}>
        {model.status === 'error' ? (
          <Tooltip content={model.error ?? 'Error'}>
            <span className={s.statusText} data-tone="error">
              <StatusDot status="error" /> Error
            </span>
          </Tooltip>
        ) : (
          <span className={s.statusText}>
            <StatusDot status={loaded ? 'active' : busy ? 'busy' : 'idle'} />
            {cloud ? 'OpenRouter' : loaded ? 'In memory' : model.status === 'loading' ? 'Loading…' : 'On disk'}
          </span>
        )}
      </div>
      <div className={s.actions}>
        {managedMemory && (
          <Button
            size="sm"
            variant={loaded ? 'outline' : 'secondary'}
            iconLeft={loaded ? <Power /> : <Play />}
            loading={busy}
            onClick={() => power.mutate({ id: model.id, action: loaded ? 'unload' : 'load' })}
          >
            {loaded ? 'Unload' : 'Load'}
          </Button>
        )}
        <IconButton label={`Open in ${meta.label}`} icon={<ArrowUpRight />} onClick={() => navigate(meta.route)} />
        <Menu
          trigger={<IconButton label="More" icon={<MoreHorizontal />} tooltip={false} />}
          items={[
            { label: 'Copy path', icon: <FolderOpen />, onSelect: () => void navigator.clipboard.writeText(model.path) },
            'separator',
            { label: cloud ? 'Unpin' : 'Delete from disk', icon: <Trash2 />, danger: true, onSelect: onDelete },
          ]}
        />
      </div>
    </motion.div>
  )
}
