import type { ComponentType, LazyExoticComponent, ReactNode } from 'react'
import { useLocation, useNavigate, useOutlet } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import { Button, EmptyState, Loader } from '@studio/ui'
import { useCapabilities } from '../api/hooks'
import type { FeatureId } from '../api/types'
import { blocked } from '../lib/capabilities'
import s from './AreaLayout.module.css'

/** One sub-section of an area (e.g. Voice → Dub). Registered in `features/<area>/sections.tsx`. */
export interface AreaSection {
  id: string
  label: string
  icon: ReactNode
  /** Group heading in the sidebar, e.g. "Create", "Voices", "Tools". Sections keep registry order within a group. */
  group: string
  description: string
  component: LazyExoticComponent<ComponentType>
  /** Feature this section needs when it differs from the area's (Voice → Dub needs "dub"). */
  needs?: FeatureId
  /** Only works on-device: hidden when the feature is reachable through a cloud provider alone. */
  local?: boolean
}

export interface AreaProps {
  /** URL segment of the area, e.g. "voice". */
  base: string
  title: string
  icon: ReactNode
  hue: string
  /** Feature the area needs; sections that can't run on this machine leave the sidebar. */
  feature?: FeatureId
  sections: AreaSection[]
}

/**
 * An area's page: the section outlet, under the area's color. The sections themselves are listed in the main
 * sidebar (they unfold under the area's entry), so a page never has more than one panel of its own beside it.
 */
export function AreaLayout({ base, title, icon, hue, feature, sections: all }: AreaProps) {
  const outlet = useOutlet()
  const location = useLocation()
  const navigate = useNavigate()
  const { data: caps } = useCapabilities()
  const off = (sec: AreaSection) => blocked(caps, sec.needs ?? feature, sec.local)
  const sections = all.filter((sec) => !off(sec))
  const current = location.pathname.split('/')[2] ?? ''
  // A direct link to a section this machine can't run explains why instead of showing a page that can't work
  const opened = all.find((sec) => sec.id === current)
  const reason = opened ? off(opened) : null

  return (
    <div className={s.area} style={{ ['--hue' as string]: hue }}>
      {reason ? (
        <EmptyState
          className={s.unavailable}
          icon={sections.length > 0 && opened ? opened.icon : icon}
          tint={hue}
          title={`${sections.length > 0 && opened ? opened.label : title} isn't available on this ${caps?.machine ?? 'machine'}`}
          description={reason}
          action={
            sections.length > 0 ? (
              <Button onClick={() => navigate(`/${base}/${sections[0].id}`)}>Open {sections[0].label}</Button>
            ) : reason.includes('key') ? (
              // a cloud key would turn it on
              <Button onClick={() => navigate('/settings')}>Open Settings</Button>
            ) : (
              <Button onClick={() => navigate('/chat')}>Back to Chat</Button>
            )
          }
        />
      ) : (
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={current}
            className={s.section}
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, transition: { duration: 0.1 } }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          >
            {outlet}
          </motion.div>
        </AnimatePresence>
      )}
    </div>
  )
}

export function SectionFallback() {
  return (
    <div className={s.fallback}>
      <Loader size={120} />
    </div>
  )
}
