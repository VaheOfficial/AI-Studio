import { useId, type ComponentType, type LazyExoticComponent, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate, useOutlet } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import { Button, EmptyState, Spinner, cn } from '@studio/ui'
import { useCapabilities } from '../api/hooks'
import type { FeatureId } from '../api/types'
import { blocked } from '../lib/capabilities'
import s from './AreaLayout.module.css'

/** One sub-section of an area (e.g. Voice → Dub). Registered in `features/<area>/sections.tsx`. */
export interface AreaSection {
  id: string
  label: string
  icon: ReactNode
  /** Rail group heading, e.g. "Create", "Voices", "Tools". Sections keep registry order within a group. */
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
  /** Feature the area needs; sections that can't run on this machine leave the rail. */
  feature?: FeatureId
  sections: AreaSection[]
}

/** Area shell: secondary navigation rail + animated section outlet. The rail hides for single-section areas. */
export function AreaLayout({ base, title, icon, hue, feature, sections: all }: AreaProps) {
  const outlet = useOutlet()
  const location = useLocation()
  const navigate = useNavigate()
  const pillId = useId()
  const { data: caps } = useCapabilities()
  const off = (sec: AreaSection) => blocked(caps, sec.needs ?? feature, sec.local)
  const sections = all.filter((sec) => !off(sec))
  const groups = [...new Set(sections.map((sec) => sec.group))]
  const current = location.pathname.split('/')[2] ?? ''
  // A direct link to a section this machine can't run explains why instead of showing a page that can't work
  const opened = all.find((sec) => sec.id === current)
  const reason = opened ? off(opened) : null

  return (
    <div className={cn(s.area, sections.length < 2 && s.single)} style={{ ['--hue' as string]: hue }}>
      {sections.length > 1 && (
        <nav className={s.rail} aria-label={`${title} sections`}>
          <div className={s.title}>
            <span className={s.titleIcon}>{icon}</span>
            <span>{title}</span>
          </div>
          {groups.map((g) => (
            <div key={g} className={s.group}>
              <div className={s.groupLabel}>{g}</div>
              {sections
                .filter((sec) => sec.group === g)
                .map((sec) => (
                  <NavLink
                    key={sec.id}
                    to={`/${base}/${sec.id}`}
                    title={sec.label}
                    className={({ isActive }) => cn(s.item, isActive && s.active)}
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && (
                          <motion.span layoutId={pillId} className={s.pill} transition={{ type: 'spring', stiffness: 500, damping: 40 }} />
                        )}
                        <span className={s.itemIcon}>{sec.icon}</span>
                        <span className={s.itemText}>
                          <span className={s.itemLabel}>{sec.label}</span>
                          <span className={s.itemDesc}>{sec.description}</span>
                        </span>
                      </>
                    )}
                  </NavLink>
                ))}
            </div>
          ))}
        </nav>
      )}
      <div className={s.content}>
        {reason ? (
          // Outside the section transition: it replaces the page the moment the capability report says so
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
    </div>
  )
}

export function SectionFallback() {
  return (
    <div className={s.fallback}>
      <Spinner size={20} />
    </div>
  )
}
