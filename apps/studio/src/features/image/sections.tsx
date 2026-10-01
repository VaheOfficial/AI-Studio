import { lazy } from 'react'
import { Image, Images, PencilLine, Sparkles } from 'lucide-react'
import type { AreaProps } from '../../components/AreaLayout'

/** Image area. Add a section by appending an entry; its id becomes the URL (`/image/<id>`). */
export const IMAGE_AREA: AreaProps = {
  base: 'image',
  title: 'Image',
  icon: <Image />,
  hue: 'var(--hue-image)',
  feature: 'image',
  sections: [
    {
      id: 'generate',
      label: 'Generate',
      icon: <Sparkles />,
      group: 'Create',
      description: 'Text to image',
      component: lazy(() => import('./GeneratePage')),
    },
    {
      id: 'edit',
      label: 'Edit',
      icon: <PencilLine />,
      group: 'Create',
      description: 'Restyle, inpaint, instruct',
      component: lazy(() => import('./EditPage')),
    },
    {
      id: 'gallery',
      label: 'Gallery',
      icon: <Images />,
      group: 'Library',
      description: 'Every image you made',
      component: lazy(() => import('./GalleryPage')),
    },
  ],
}
