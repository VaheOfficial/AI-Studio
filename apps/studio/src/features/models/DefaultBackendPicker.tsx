import { SegmentedControl, StatusDot } from '@studio/ui'
import type { LocalBackend } from '../../api/contracts/hub'
import type { LocalBackendId } from '../../api/types'
import { BACKEND_NAME, BACKEND_ORDER, backendState } from './hubMeta'

/** Which engine GGUF language models install to and chat through by default. */
export function DefaultBackendPicker({
  value,
  onValueChange,
  backends,
  size,
}: {
  value: LocalBackendId
  onValueChange: (v: LocalBackendId) => void
  backends: LocalBackend[]
  size?: 'sm' | 'md'
}) {
  return (
    <SegmentedControl<LocalBackendId>
      aria-label="Default local engine"
      size={size}
      value={value}
      onValueChange={onValueChange}
      segments={BACKEND_ORDER.map((id) => {
        const state = backendState(backends.find((b) => b.id === id))
        return { value: id, label: BACKEND_NAME[id], icon: <StatusDot status={state.dot} />, title: `${BACKEND_NAME[id]}: ${state.text}` }
      })}
    />
  )
}
