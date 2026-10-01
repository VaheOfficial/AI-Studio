import { useSetRoot } from '../../../api/workspace'
import { FolderDialog } from '../../../components/FolderDialog'

export interface FolderPickerProps {
  onClose: () => void
  sessionId?: string
  current?: string
  /** For a chat that doesn't exist yet the choice is kept as a draft. */
  onDraft: (root: string) => void
}

/** The chat's workspace folder, chosen with the shared folder browser. */
export function FolderPicker({ onClose, sessionId, current, onDraft }: FolderPickerProps) {
  const setRoot = useSetRoot()
  return (
    <FolderDialog
      title="Workspace folder"
      description="The agent's files, terminal and memory live here. It can read and change anything inside — pick a project folder, not a whole drive."
      initial={current}
      onClose={onClose}
      onChoose={async (root) => {
        if (sessionId) await setRoot.mutateAsync({ sid: sessionId, root })
        else onDraft(root)
      }}
    />
  )
}
