import { AudioLines, Ear, Eye, Image, ImagePlus, Layers, MessageSquareText, Music, Waves } from 'lucide-react'
import type { Chip } from '@studio/ui'
import type { HubTask, LocalBackend } from '../../api/contracts/hub'
import type { RepoRef } from '../../api/hub'
import type { CatalogEntry, Fit, LocalBackendId, WeightFormat } from '../../api/types'

export const FIT: Record<Fit, { label: string; tone: 'success' | 'warning' | 'danger'; hint: string }> = {
  yes: { label: 'Runs great', tone: 'success', hint: 'Fits entirely in your GPU memory.' },
  offload: { label: 'Needs offload', tone: 'warning', hint: 'Runs by spilling weights to system RAM. Works, but slower.' },
  no: { label: 'Too large', tone: 'danger', hint: 'Exceeds this machine’s combined VRAM + RAM.' },
}

export const FORMAT_LABEL: Record<WeightFormat, string> = {
  gguf: 'GGUF',
  safetensors: 'safetensors',
  diffusers: 'Diffusers',
  ollama: 'Ollama',
  onnx: 'ONNX',
  ct2: 'CTranslate2',
  other: 'Other',
}

export type TaskFilter = HubTask | 'all'

export const TASK_CHIPS: Chip<TaskFilter>[] = [
  { value: 'all', label: 'All', icon: <Layers /> },
  { value: 'text-generation', label: 'Chat', icon: <MessageSquareText />, color: 'var(--hue-text)' },
  { value: 'image-text-to-text', label: 'Vision chat', icon: <Eye />, color: 'var(--hue-text)' },
  { value: 'text-to-image', label: 'Text → image', icon: <Image />, color: 'var(--hue-image)' },
  { value: 'image-to-image', label: 'Image → image', icon: <ImagePlus />, color: 'var(--hue-image)' },
  { value: 'text-to-speech', label: 'Speech', icon: <AudioLines />, color: 'var(--hue-voice)' },
  { value: 'automatic-speech-recognition', label: 'Transcription', icon: <Ear />, color: 'var(--hue-stt)' },
  { value: 'text-to-audio', label: 'Music & audio', icon: <Music />, color: 'var(--hue-music)' },
  { value: 'audio-to-audio', label: 'Audio → audio', icon: <Waves />, color: 'var(--hue-voice)' },
]

export const BACKEND_ORDER: LocalBackendId[] = ['lmstudio', 'llamacpp', 'ollama']
export const BACKEND_NAME: Record<LocalBackendId, string> = { lmstudio: 'LM Studio', llamacpp: 'llama.cpp', ollama: 'Ollama' }

export function backendState(b: LocalBackend | undefined): { dot: 'active' | 'idle' | 'off'; text: string } {
  if (!b?.installed) return { dot: 'off', text: 'Not installed' }
  return b.running ? { dot: 'active', text: 'Running' } : { dot: 'idle', text: 'Installed' }
}

/** The hub repo behind a curated catalog entry: its Hugging Face repo or Ollama library model. */
export function catalogRepo({ source }: CatalogEntry): RepoRef | null {
  const [repo] = source.repo.split(':')
  if (source.type === 'ollama') {
    // Ollama can pull GGUFs straight from Hugging Face: "hf.co/<org>/<repo>:<quant>"
    return repo.startsWith('hf.co/') ? { source: 'hf', id: repo.slice('hf.co/'.length) } : { source: 'ollama', id: repo }
  }
  return repo.includes('/') ? { source: 'hf', id: repo } : null
}

/** Licenses that forbid commercial use (FLUX.1-dev, CC-BY-NC, …) — shown as a warning badge. */
export const isNonCommercial = (license?: string) => !!license && /non[-_ ]?commercial|(^|-)nc(-|$)/i.test(license)
