import { useMemo, useState } from 'react'
import { ChevronRight, FileDiff, FileText, Folder, FolderOpen, RotateCcw, Save, WrapText } from 'lucide-react'
import { Badge, Button, CodeEditor, DiffView, EmptyState, IconButton, Skeleton, Spinner, cn } from '@studio/ui'
import type { FsEntry, ToolDisplay } from '../../../api/contracts/workspace'
import { useDir, useFile, useSaveFile } from '../../../api/workspace'
import { formatBytes } from '../../../lib/format'
import { useWorkspacePanel } from './panel'
import s from './FilesTab.module.css'

type Diff = Extract<ToolDisplay, { kind: 'diff' }>

function DirNode({ sid, entry, depth, selected, onOpen }: { sid: string; entry: FsEntry; depth: number; selected?: string; onOpen: (p: string) => void }) {
  const [open, setOpen] = useState(false)
  const pad = { paddingLeft: 8 + depth * 12 }
  if (entry.type === 'file') {
    return (
      <button className={cn(s.node, selected === entry.path && s.selected)} style={pad} onClick={() => onOpen(entry.path)} title={entry.path}>
        <FileText size={13} className={s.fileIcon} />
        <span>{entry.name}</span>
      </button>
    )
  }
  return (
    <>
      <button className={s.node} style={pad} onClick={() => setOpen(!open)} aria-expanded={open}>
        <ChevronRight size={12} className={cn(s.chev, open && s.chevOpen)} />
        {open ? <FolderOpen size={13} className={s.dirIcon} /> : <Folder size={13} className={s.dirIcon} />}
        <span>{entry.name}</span>
      </button>
      {open && <DirChildren sid={sid} path={entry.path} depth={depth + 1} selected={selected} onOpen={onOpen} />}
    </>
  )
}

function DirChildren({ sid, path, depth, selected, onOpen }: { sid: string; path: string; depth: number; selected?: string; onOpen: (p: string) => void }) {
  const { data, isLoading, error } = useDir(sid, path, true)
  if (isLoading) return <div className={s.loadingRow} style={{ paddingLeft: 8 + depth * 12 }}><Spinner size={11} /></div>
  if (error) return <p className={s.treeError}>{error.message}</p>
  if (!data?.entries.length) return depth === 0 ? <p className={s.treeEmpty}>Empty folder</p> : null
  return (
    <>
      {data.entries.map((e) => (
        <DirNode key={e.path} sid={sid} entry={e} depth={depth} selected={selected} onOpen={onOpen} />
      ))}
    </>
  )
}

function Editor({ sid, path, diffs }: { sid: string; path: string; diffs: Diff[] }) {
  const { data: file, isLoading, error, refetch } = useFile(sid, path)
  const save = useSaveFile(sid)
  const [draft, setDraft] = useState<string>()
  const [showChanges, setShowChanges] = useState(false)
  const wrap = useWorkspacePanel((st) => st.wrap)
  const setWrap = useWorkspacePanel((st) => st.setWrap)
  const changes = useMemo(() => diffs.filter((d) => d.path === path), [diffs, path])
  const dirty = draft !== undefined && draft !== file?.content
  const readOnly = !file || file.binary || file.truncated
  const doSave = () => {
    if (dirty && draft !== undefined) save.mutate({ path, content: draft }, { onSuccess: () => setDraft(undefined) })
  }

  return (
    <div className={s.editor}>
      <div className={s.editorBar}>
        <span className={s.editorPath} title={path}>
          {path}
        </span>
        {dirty && <Badge tone="warning" size="sm">unsaved</Badge>}
        {file && <span className={s.meta}>{formatBytes(file.size)}</span>}
        {changes.length > 0 && (
          <Button size="sm" variant={showChanges ? 'secondary' : 'ghost'} iconLeft={<FileDiff />} onClick={() => setShowChanges(!showChanges)}>
            Agent changes ({changes.length})
          </Button>
        )}
        <IconButton label={wrap ? 'Word wrap: on' : 'Word wrap: off'} icon={<WrapText />} size="sm" active={wrap} onClick={() => setWrap(!wrap)} />
        {dirty && <IconButton label="Discard edits" icon={<RotateCcw />} size="sm" onClick={() => setDraft(undefined)} />}
        <IconButton label="Save (Ctrl+S)" icon={<Save />} size="sm" disabled={!dirty || readOnly} onClick={doSave} />
      </div>
      {isLoading ? (
        <div className={s.editorLoading}>
          <Skeleton height={14} width="60%" />
          <Skeleton height={14} width="80%" />
          <Skeleton height={14} width="40%" />
        </div>
      ) : error ? (
        <EmptyState title="Can't open this file" description={error.message} action={<Button onClick={() => void refetch()}>Retry</Button>} />
      ) : file?.binary ? (
        <EmptyState icon={<FileText />} title="Binary file" description={`${formatBytes(file.size)} — not shown as text.`} />
      ) : showChanges ? (
        <div className={s.changes}>
          {changes.map((d, i) => (
            <div key={i} className={s.change}>
              <div className={s.changeHead}>
                Change {i + 1} {d.created && '(created)'} <span className={s.added}>+{d.added}</span> <span className={s.removed}>−{d.removed}</span>
              </div>
              <DiffView diff={d.diff} wrap={wrap} />
            </div>
          ))}
        </div>
      ) : (
        <>
          {file?.truncated && <p className={s.notice}>Large file: showing the first 1 MB, read-only.</p>}
          <CodeEditor value={draft ?? file?.content ?? ''} filename={path} readOnly={readOnly} onChange={setDraft} onSave={doSave} wrap={wrap} className={s.cm} />
        </>
      )}
    </div>
  )
}

export function FilesTab({ sessionId, root, diffs, onPickFolder }: { sessionId: string; root?: string; diffs: Diff[]; onPickFolder: () => void }) {
  const { filePath, showFile } = useWorkspacePanel()
  if (!root) {
    return (
      <EmptyState
        icon={<FolderOpen />}
        title="No folder chosen"
        description="Pick the folder this chat works in to browse and edit its files."
        action={<Button variant="secondary" onClick={onPickFolder}>Choose folder</Button>}
      />
    )
  }
  return (
    <div className={s.files}>
      <nav className={s.tree} aria-label="Workspace files">
        <DirChildren sid={sessionId} path="." depth={0} selected={filePath} onOpen={showFile} />
      </nav>
      <div className={s.main}>
        {filePath ? (
          <Editor key={filePath} sid={sessionId} path={filePath} diffs={diffs} />
        ) : (
          <EmptyState icon={<FileText />} title="Open a file" description="Pick a file on the left, or click a file in a tool card." />
        )}
      </div>
    </div>
  )
}
