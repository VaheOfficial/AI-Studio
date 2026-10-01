import { lazy } from 'react'
import { Clapperboard, Film } from 'lucide-react'
import type { AreaProps } from '../../components/AreaLayout'

/** Video area. Add a section by appending an entry; its id becomes the URL (`/video/<id>`). */
export const VIDEO_AREA: AreaProps = {
  base: 'video',
  title: 'Video',
  icon: <Clapperboard />,
  hue: 'var(--hue-video)',
  feature: 'video',
  sections: [
    {
      id: 'create',
      label: 'Create',
      icon: <Film />,
      group: 'Create',
      description: 'Clips from a prompt or an image',
      component: lazy(() => import('./VideoPage')),
    },
  ],
}
