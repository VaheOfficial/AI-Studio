import { useState, type ReactNode } from 'react'
import { ArrowUp, Folder, FolderPlus, HardDrive } from 'lucide-react'
import { Button, Dialog, IconButton, Input, Skeleton } from '@studio/ui'
import { useFolders, useMakeFolder } from '../api/workspace'
import s from './FolderDialog.module.css'

export interface FolderDialogProps {
  title: string
  description?: ReactNode
  /** Folder the browser starts in (and the pre-filled choice). */
  initial?: string
  confirmLabel?: string
  placeholder?: string
  onClose: () => void
  /** Called with the chosen path; the dialog closes when it resolves. */
  onChoose: (path: string) => void | Promise<void>
}

/**
 * Server-side folder browser (the browser can't reveal real paths), with typed paths and "New folder".
 * Mount it only while it is shown: every opening starts at `initial`.
 */
export function FolderDialog({ title, description, initial, confirmLabel = 'Use this folder', placeholder, onClose, onChoose }: FolderDialogProps) {
  const [path, setPath] = useState(initial ?? '')
  const [typed, setTyped] = useState(initial ?? '')
  const [newName, setNewName] = useState<string>()
  const [busy, setBusy] = useState(false)
  const { data, isLoading, error } = useFolders(path, true)
  const mkdir = useMakeFolder()

  const go = (p: string) => {
    setPath(p)
    setTyped(p)
  }

  const choose = async () => {
    const target = typed.trim()
    if (!target) return
    setBusy(true)
    try {
      await onChoose(target)
      onClose()
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={title}
      description={description}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!typed.trim()} loading={busy} onClick={() => void choose()}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className={s.picker}>
        <div className={s.pathRow}>
          <IconButton label="Up" icon={<ArrowUp />} size="sm" disabled={!data?.path} onClick={() => go(data?.parent ?? '')} />
          <Input
            size="sm"
            className={s.path}
            value={typed}
            placeholder={placeholder ?? 'C:\\Users\\you\\projects\\my-app'}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && go(typed.trim())}
            spellCheck={false}
          />
          <IconButton label="New folder here" icon={<FolderPlus />} size="sm" disabled={!data?.path} onClick={() => setNewName('')} />
        </div>
        {newName !== undefined && data?.path && (
          <form
            className={s.pathRow}
            onSubmit={async (e) => {
              e.preventDefault()
              const listing = await mkdir.mutateAsync({ parent: data.path, name: newName })
              setNewName(undefined)
              go(listing.path)
            }}
          >
            <Input size="sm" className={s.path} autoFocus value={newName} placeholder="Folder name" onChange={(e) => setNewName(e.target.value)} />
            <Button size="sm" type="submit" variant="secondary" loading={mkdir.isPending} disabled={!newName.trim()}>
              Create
            </Button>
          </form>
        )}
        <div className={s.list} role="listbox" aria-label="Folders">
          {isLoading ? (
            <>
              <Skeleton height={26} />
              <Skeleton height={26} />
              <Skeleton height={26} />
            </>
          ) : error ? (
            <p className={s.error}>{error.message}</p>
          ) : data?.dirs.length ? (
            data.dirs.map((d) => (
              <button key={d.path} className={s.item} onDoubleClick={() => go(d.path)} onClick={() => setTyped(d.path)} data-selected={typed === d.path || undefined}>
                {data.path ? <Folder size={14} /> : <HardDrive size={14} />}
                <span>{d.name}</span>
              </button>
            ))
          ) : (
            <p className={s.empty}>No subfolders</p>
          )}
        </div>
        <p className={s.hint}>Click to select, double-click to open. You can also type or paste a path.</p>
      </div>
    </Dialog>
  )
}
