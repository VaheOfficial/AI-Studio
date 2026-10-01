import type { ReactNode } from 'react'
import { AudioLines, Clapperboard, Ear, Image, MessageSquareText, Music } from 'lucide-react'
import type { ModelKind } from '../api/types'

export interface KindMeta {
  label: string
  plural: string
  icon: ReactNode
  /** CSS var for the modality hue. */
  hue: string
  /** Concrete colors for canvas effects (Aurora can't read CSS vars). */
  aurora: string[]
  route: string
}

export const KINDS: Record<ModelKind, KindMeta> = {
  text: {
    label: 'Text',
    plural: 'Language models',
    icon: <MessageSquareText />,
    hue: 'var(--hue-text)',
    aurora: ['#7c3aed', '#4f46e5', '#a78bfa'],
    route: '/chat',
  },
  image: {
    label: 'Image',
    plural: 'Image models',
    icon: <Image />,
    hue: 'var(--hue-image)',
    aurora: ['#f59e0b', '#ef4444', '#f97316'],
    route: '/image',
  },
  voice: {
    label: 'Voice',
    plural: 'Voice models',
    icon: <AudioLines />,
    hue: 'var(--hue-voice)',
    aurora: ['#14b8a6', '#0ea5e9', '#10b981'],
    route: '/voice',
  },
  stt: {
    label: 'Speech-to-text',
    plural: 'Transcription models',
    icon: <Ear />,
    hue: 'var(--hue-stt)',
    aurora: ['#0ea5e9', '#6366f1'],
    route: '/voice/transcribe',
  },
  music: {
    label: 'Music',
    plural: 'Music models',
    icon: <Music />,
    hue: 'var(--hue-music)',
    aurora: ['#ec4899', '#a855f7', '#f43f5e'],
    route: '/music',
  },
  video: {
    label: 'Video',
    plural: 'Video models',
    icon: <Clapperboard />,
    hue: 'var(--hue-video)',
    aurora: ['#ef4444', '#f97316', '#e11d48'],
    route: '/video',
  },
}

export const KIND_ORDER: ModelKind[] = ['text', 'image', 'voice', 'stt', 'music', 'video']
