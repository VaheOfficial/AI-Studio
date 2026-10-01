import { lazy } from 'react'
import { Layers, Music, Music2 } from 'lucide-react'
import type { AreaProps } from '../../components/AreaLayout'

/** Music area. Add a section by appending an entry; its id becomes the URL (`/music/<id>`). */
export const MUSIC_AREA: AreaProps = {
  base: 'music',
  title: 'Music',
  icon: <Music />,
  hue: 'var(--hue-music)',
  feature: 'music',
  sections: [
    {
      id: 'create',
      label: 'Create',
      icon: <Music2 />,
      group: 'Create',
      description: 'Songs from a prompt',
      component: lazy(() => import('./MusicPage')),
    },
    {
      id: 'stems',
      label: 'Stems',
      icon: <Layers />,
      group: 'Tools',
      description: 'Split a song into stems',
      needs: 'dub',
      component: lazy(() => import('../audio-tools/IsolatePage').then((m) => ({ default: m.StemsTab }))),
    },
  ],
}
