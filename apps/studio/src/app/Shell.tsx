import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useMatch, useNavigate, useOutlet } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import { AlarmClock, ArrowUpCircle, AudioLines, Boxes, Clapperboard, House, Image, MessageSquareText, Moon, MoreHorizontal, Music, PanelLeft, Pencil, Plus, ScrollText, Search, Settings, Skull, Sun, Swords, Trash2, Trophy } from 'lucide-react'
import { CommandPalette, ConfirmDialog, IconButton, Kbd, Logo, Menu, StatusDot, Tooltip, cn, type CommandAction } from '@studio/ui'
import type { GameSummary } from '../api/contracts/game'
import { useDeleteGame, useGames } from '../api/game'
import { useCapabilities, useDeleteSession, useSessions, useUpdateSession } from '../api/hooks'
import type { AgentSession, FeatureId } from '../api/types'
import { useLive, useRealtime } from '../api/live'
import type { AreaProps } from '../components/AreaLayout'
import { IMAGE_AREA } from '../features/image/sections'
import { MUSIC_AREA } from '../features/music/sections'
import { VIDEO_AREA } from '../features/video/sections'
import { VOICE_AREA } from '../features/voice/sections'
import { CreditPill } from '../features/openrouter/CreditPill'
import { blocked } from '../lib/capabilities'
import { useUpdates } from '../lib/desktop'
import { formatBytes } from '../lib/format'
import { shortcut } from '../lib/platform'
import { useUI } from '../stores/ui'
import { JobsTray } from './JobsTray'
import s from './Shell.module.css'

interface NavItem {
  to: string
  label: string
  icon: ReactNode
  hue?: string
  shortcut?: string
  /** Hidden on machines that can't run it. */
  feature?: FeatureId
  /** An area with sections of its own: they unfold under this entry while the area is open. */
  area?: AreaProps
}

const NAV: NavItem[] = [
  { to: '/', label: 'Home', icon: <House />, shortcut: '1' },
  { to: '/chat', label: 'Chat', icon: <MessageSquareText />, hue: 'var(--hue-text)', shortcut: '2' },
  { to: '/image', label: 'Image', icon: <Image />, hue: 'var(--hue-image)', shortcut: '3', feature: 'image', area: IMAGE_AREA },
  { to: '/voice', label: 'Voice', icon: <AudioLines />, hue: 'var(--hue-voice)', shortcut: '4', feature: 'voice', area: VOICE_AREA },
  { to: '/music', label: 'Music', icon: <Music />, hue: 'var(--hue-music)', shortcut: '5', feature: 'music', area: MUSIC_AREA },
  { to: '/video', label: 'Video', icon: <Clapperboard />, hue: 'var(--hue-video)', shortcut: '8', feature: 'video', area: VIDEO_AREA },
  { to: '/models', label: 'Models', icon: <Boxes />, shortcut: '6' },
  { to: '/game', label: 'Game', icon: <Swords />, hue: 'var(--hue-game)', shortcut: '7', feature: 'game' },
  { to: '/automations', label: 'Automations', icon: <AlarmClock />, shortcut: '9' },
]

/** The pages this machine can run (everything, until the capability report has loaded). */
function useNav(): NavItem[] {
  const { data: caps } = useCapabilities()
  return useMemo(() => NAV.filter((n) => !blocked(caps, n.feature)), [caps])
}

const FOOTER_NAV: NavItem[] = [
  { to: '/logs', label: 'Logs', icon: <ScrollText /> },
  { to: '/settings', label: 'Settings', icon: <Settings />, shortcut: ',' },
]

export function Shell() {
  useRealtime()
  const { sidebarCollapsed, toggleSidebar, commandOpen, setCommandOpen, theme, setTheme } = useUI()
  const navigate = useNavigate()
  const location = useLocation()
  const outlet = useOutlet()
  const nav = useNav()

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  // Global shortcuts: ⌘K palette, ⌘1..6 pages, ⌘, settings, ⌘B sidebar
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return
      const k = e.key.toLowerCase()
      if (k === 'k') {
        e.preventDefault()
        setCommandOpen(!useUI.getState().commandOpen)
        return
      }
      if (k === 'b') {
        e.preventDefault()
        toggleSidebar()
        return
      }
      const item = [...nav, ...FOOTER_NAV].find((n) => n.shortcut === k)
      if (item) {
        e.preventDefault()
        navigate(item.to)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [nav, navigate, setCommandOpen, toggleSidebar])

  const actions = useCommandActions()
  // Animate between sections, not between sub-routes like /chat/:id
  const section = '/' + (location.pathname.split('/')[1] ?? '')
  // The glow behind the page takes the color of the area that is open
  const hue = nav.find((n) => n.to === section)?.hue

  return (
    <div className={cn(s.shell, sidebarCollapsed && s.collapsed)}>
      <aside className={s.sidebar}>
        <Brand collapsed={sidebarCollapsed} />

        <button className={s.search} onClick={() => setCommandOpen(true)}>
          <Search size={15} />
          {!sidebarCollapsed && (
            <>
              <span>Search or run…</span>
              <Kbd>{shortcut('K')}</Kbd>
            </>
          )}
        </button>

        <div className={s.navScroll}>
          <nav className={s.nav} aria-label="Main">
            {nav.map((item) => (
              <Fragment key={item.to}>
                <SideLink item={item} collapsed={sidebarCollapsed} />
                {item.area && <AreaSections area={item.area} collapsed={sidebarCollapsed} />}
                {item.to === '/game' && <Adventures collapsed={sidebarCollapsed} />}
              </Fragment>
            ))}
          </nav>

          {!sidebarCollapsed && <RecentChats />}
        </div>

        <div className={s.sidebarFooter}>
          {FOOTER_NAV.map((item) => (
            <SideLink key={item.to} item={item} collapsed={sidebarCollapsed} />
          ))}
          <GpuMeter collapsed={sidebarCollapsed} />
        </div>
      </aside>

      <div className={s.main} style={hue ? { ['--area-hue' as string]: hue } : undefined}>
        <header className={s.topbar}>
          <IconButton label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'} icon={<PanelLeft />} onClick={toggleSidebar} tooltipSide="bottom" />
          <div className={s.topbarSpacer} />
          <CreditPill />
          <UpdatePill />
          <ConnectionPill />
          <JobsTray />
          <IconButton
            label={theme === 'dark' ? 'Light mode' : 'Dark mode'}
            icon={theme === 'dark' ? <Sun /> : <Moon />}
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            tooltipSide="bottom"
          />
        </header>
        <main className={s.content}>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={section}
              className={s.page}
              initial={{ opacity: 0, y: 8, filter: 'blur(4px)' }}
              animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
              exit={{ opacity: 0, y: -4, filter: 'blur(2px)', transition: { duration: 0.12 } }}
              transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
            >
              {outlet}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} actions={actions} />
    </div>
  )
}

/** The sections of an area this machine can run. */
function useAreaSections(area: AreaProps | undefined) {
  const { data: caps } = useCapabilities()
  return useMemo(() => (area ? area.sections.filter((sec) => !blocked(caps, sec.needs ?? area.feature, sec.local)) : []), [area, caps])
}

function SideLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  // Plain className/children (not NavLink's render functions): the collapsed rail's Tooltip trigger merges props
  // as strings and would turn a className function into garbage, leaving the link unstyled.
  const isActive = !!useMatch({ path: item.to, end: item.to === '/' })
  // An open area hands the highlight to its section below; its own entry only stays lit
  const sections = useAreaSections(item.area)
  const unfolded = isActive && sections.length > 1
  const link = (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={cn(s.navItem, isActive && s.navActive, unfolded && s.navOpen)}
      style={item.hue ? { ['--hue' as string]: item.hue } : undefined}
    >
      {isActive && !unfolded && <motion.span layoutId="nav-active" className={s.navPill} transition={{ type: 'spring', stiffness: 500, damping: 40 }} />}
      <span className={s.navIcon}>{item.icon}</span>
      {!collapsed && <span className={s.navLabel}>{item.label}</span>}
      {!collapsed && item.shortcut && <span className={s.navShortcut}>{shortcut(item.shortcut)}</span>}
    </NavLink>
  )
  return collapsed ? (
    <Tooltip content={item.label} side="right">
      {link}
    </Tooltip>
  ) : (
    link
  )
}

/**
 * An area's sections, unfolded under its entry while the area is open (so the page itself needs no navigation
 * panel of its own). With the sidebar collapsed they stay as icons.
 */
function AreaSections({ area, collapsed }: { area: AreaProps; collapsed: boolean }) {
  const sections = useAreaSections(area)
  const open = !!useMatch({ path: `/${area.base}`, end: false })
  const groups = [...new Set(sections.map((sec) => sec.group))]
  return (
    <AnimatePresence initial={false}>
      {open && sections.length > 1 && (
        <motion.div
          className={s.subnav}
          style={{ ['--hue' as string]: area.hue }}
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
        >
          {groups.map((group) => (
            <Fragment key={group}>
              {!collapsed && groups.length > 1 && <div className={s.subGroup}>{group}</div>}
              {sections
                .filter((sec) => sec.group === group)
                .map((sec) => (
                  <SubLink key={sec.id} to={`/${area.base}/${sec.id}`} label={sec.label} description={sec.description} icon={sec.icon} collapsed={collapsed} />
                ))}
            </Fragment>
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function SubLink({ to, label, description, icon, collapsed, end = false }: { to: string; label: string; description: string; icon: ReactNode; collapsed: boolean; end?: boolean }) {
  const isActive = !!useMatch({ path: to, end })
  const link = (
    <NavLink to={to} end={end} className={cn(s.subItem, isActive && s.subActive)} title={collapsed ? undefined : description}>
      {isActive && <motion.span layoutId="nav-active" className={s.navPill} transition={{ type: 'spring', stiffness: 500, damping: 40 }} />}
      <span className={s.navIcon}>{icon}</span>
      {!collapsed && <span className={s.navLabel}>{label}</span>}
    </NavLink>
  )
  return collapsed ? (
    <Tooltip content={`${label} — ${description}`} side="right">
      {link}
    </Tooltip>
  ) : (
    link
  )
}

/**
 * Saved adventures, unfolded under Game while it is open, so the game page keeps a single panel of its own (the
 * character sheet). With the sidebar collapsed only "New adventure" stays; the rest are in the command palette.
 */
function Adventures({ collapsed }: { collapsed: boolean }) {
  const open = !!useMatch({ path: '/game', end: false })
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          className={s.subnav}
          style={{ ['--hue' as string]: 'var(--hue-game)' }}
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
        >
          <AdventureList collapsed={collapsed} />
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function AdventureList({ collapsed }: { collapsed: boolean }) {
  const { data: games = [] } = useGames()
  return (
    <>
      <SubLink to="/game" end label="New adventure" description="Start a new story" icon={<Plus />} collapsed={collapsed} />
      {!collapsed && games.length > 0 && <div className={s.subGroup}>Adventures</div>}
      {!collapsed && games.map((g) => <Adventure key={g.id} game={g} />)}
    </>
  )
}

function Adventure({ game }: { game: GameSummary }) {
  const navigate = useNavigate()
  const active = !!useMatch(`/game/${game.id}`)
  const remove = useDeleteGame()
  const [confirming, setConfirming] = useState(false)
  const meta = `Lv ${game.level} ${game.role} · ${game.turns} ${game.turns === 1 ? 'turn' : 'turns'}`
  return (
    <div className={cn(s.subItem, s.subRow, active && s.subActive)}>
      {active && <motion.span layoutId="nav-active" className={s.navPill} transition={{ type: 'spring', stiffness: 500, damping: 40 }} />}
      <NavLink to={`/game/${game.id}`} className={s.subRowLink} title={`${game.title} — ${meta}`}>
        <span className={s.navLabel}>{game.title}</span>
        {game.status === 'dead' && <Skull className={s.subFallen} aria-label="Fallen" />}
        {game.status === 'won' && <Trophy className={s.subWon} aria-label="Won" />}
      </NavLink>
      <span className={s.recentMenu}>
        <Menu
          trigger={<IconButton size="sm" label="Adventure actions" icon={<MoreHorizontal />} />}
          items={[{ label: 'Delete', icon: <Trash2 size={14} />, danger: true, onSelect: () => setConfirming(true) }]}
        />
      </span>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Delete this adventure?"
        description={`“${game.title}” and its whole story are deleted.`}
        confirmLabel="Delete"
        tone="danger"
        onConfirm={async () => {
          await remove.mutateAsync(game.id)
          if (active) navigate('/game')
        }}
      />
    </div>
  )
}

function RecentChats() {
  const { data } = useSessions()
  const navigate = useNavigate()
  const recent = data ?? []
  return (
    <div className={s.recent}>
      <div className={s.sectionLabel}>
        <span>Recent chats</span>
        <IconButton size="sm" label="New chat" icon={<Plus />} onClick={() => navigate('/chat')} />
      </div>
      {recent.length === 0 ? <p className={s.recentEmpty}>No conversations yet</p> : recent.map((c) => <RecentChat key={c.id} chat={c} />)}
    </div>
  )
}

function RecentChat({ chat }: { chat: AgentSession }) {
  const navigate = useNavigate()
  const active = !!useMatch(`/chat/${chat.id}`)
  const rename = useUpdateSession()
  const remove = useDeleteSession()
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const title = chat.title || 'Untitled'
  const commit = (value: string) => {
    setEditing(false)
    const next = value.trim()
    if (next && next !== chat.title) rename.mutate({ id: chat.id, title: next })
  }
  return (
    <div className={cn(s.recentItem, active && s.recentActive)}>
      {editing ? (
        <input
          className={s.recentRename}
          aria-label="Chat name"
          defaultValue={title}
          autoFocus
          onFocus={(e) => e.currentTarget.select()}
          onBlur={(e) => commit(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur()
            if (e.key === 'Escape') setEditing(false)
          }}
        />
      ) : (
        <NavLink to={`/chat/${chat.id}`} className={s.recentLink} title={title}>
          {title}
        </NavLink>
      )}
      {!editing && (
        <span className={s.recentMenu}>
          <Menu
            trigger={<IconButton size="sm" label="Chat actions" icon={<MoreHorizontal />} />}
            items={[
              { label: 'Rename', icon: <Pencil size={14} />, onSelect: () => setEditing(true) },
              { label: 'Delete', icon: <Trash2 size={14} />, danger: true, onSelect: () => setConfirming(true) },
            ]}
          />
        </span>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Delete this chat?"
        description={`“${title}” and its messages are deleted; its terminals and browser page close. Files in its workspace folder stay.`}
        confirmLabel="Delete"
        tone="danger"
        onConfirm={async () => {
          await remove.mutateAsync(chat.id)
          if (active) navigate('/chat')
        }}
      />
    </div>
  )
}

function GpuMeter({ collapsed }: { collapsed: boolean }) {
  const data = useLive((st) => st.system)
  const gpu = data?.gpus[0]
  if (!data) return null
  if (!gpu) return <MemoryMeter collapsed={collapsed} used={data.ram_used} total={data.ram_total} cpu={data.cpu_percent} />
  const frac = gpu.vram_used / gpu.vram_total
  const ramFrac = data.ram_used / data.ram_total
  const tone = frac > 0.9 ? 'var(--danger)' : frac > 0.7 ? 'var(--warning)' : 'var(--accent)'
  const meter = (
    <div className={s.gpu} style={{ ['--tone' as string]: tone }}>
      {!collapsed && (
        <div className={s.gpuHead}>
          <span className={s.gpuName}>{gpu.name.replace('NVIDIA GeForce ', '')}</span>
          <span className={s.gpuUtil}>{Math.round(gpu.util)}%</span>
        </div>
      )}
      <div className={s.gpuBar}>
        <motion.div className={s.gpuFill} animate={{ width: `${frac * 100}%` }} transition={{ type: 'spring', stiffness: 80, damping: 20 }} />
      </div>
      {!collapsed && (
        <div className={s.gpuFoot}>
          <span>VRAM {formatBytes(gpu.vram_used, 1)} / {formatBytes(gpu.vram_total, 0)}</span>
          <span>RAM {Math.round(ramFrac * 100)}%</span>
        </div>
      )}
    </div>
  )
  return collapsed ? (
    <Tooltip content={`VRAM ${formatBytes(gpu.vram_used)} / ${formatBytes(gpu.vram_total)}`} side="right">
      {meter}
    </Tooltip>
  ) : (
    meter
  )
}

/** The sidebar meter on a machine without an NVIDIA GPU: system memory instead of VRAM. */
function MemoryMeter({ collapsed, used, total, cpu }: { collapsed: boolean; used: number; total: number; cpu: number }) {
  const frac = used / total
  const tone = frac > 0.9 ? 'var(--danger)' : frac > 0.75 ? 'var(--warning)' : 'var(--accent)'
  const meter = (
    <div className={s.gpu} style={{ ['--tone' as string]: tone }}>
      {!collapsed && (
        <div className={s.gpuHead}>
          <span className={s.gpuName}>Memory</span>
          <span className={s.gpuUtil}>{Math.round(frac * 100)}%</span>
        </div>
      )}
      <div className={s.gpuBar}>
        <motion.div className={s.gpuFill} animate={{ width: `${frac * 100}%` }} transition={{ type: 'spring', stiffness: 80, damping: 20 }} />
      </div>
      {!collapsed && (
        <div className={s.gpuFoot}>
          <span>RAM {formatBytes(used, 1)} / {formatBytes(total, 0)}</span>
          <span>CPU {Math.round(cpu)}%</span>
        </div>
      )}
    </div>
  )
  return collapsed ? (
    <Tooltip content={`RAM ${formatBytes(used)} / ${formatBytes(total)}`} side="right">
      {meter}
    </Tooltip>
  ) : (
    meter
  )
}

/** Desktop app: a newer release exists. Opens Settings, where it is installed. */
function UpdatePill() {
  const { data } = useUpdates()
  const navigate = useNavigate()
  if (!data?.available && !data?.needsInstaller) return null
  return (
    <Tooltip content={`Version ${data.latest} is available`} side="bottom">
      <button className={cn(s.conn, s.connUpdate)} onClick={() => navigate('/settings')}>
        <ArrowUpCircle size={13} />
        <span>Update</span>
      </button>
    </Tooltip>
  )
}

function ConnectionPill() {
  const status = useLive((st) => st.status)
  const version = useLive((st) => st.version)
  const ok = status === 'open'
  return (
    <Tooltip content={ok ? `Server v${version} · live` : 'Start the server: pnpm server'} side="bottom">
      <div className={cn(s.conn, !ok && s.connOff)}>
        <StatusDot status={ok ? 'active' : status === 'connecting' ? 'busy' : 'error'} />
        <span>{ok ? 'Local' : status === 'connecting' ? 'Connecting' : 'Offline'}</span>
      </div>
    </Tooltip>
  )
}

function useCommandActions(): CommandAction[] {
  const navigate = useNavigate()
  const { data: sessions } = useSessions()
  const { data: games } = useGames()
  const { setTheme, theme, toggleSidebar } = useUI()
  const { data: caps } = useCapabilities()
  const pages = useNav()
  return useMemo(() => {
    const nav: CommandAction[] = [...pages, ...FOOTER_NAV].map((n) => ({
      id: `nav-${n.to}`,
      label: `Go to ${n.label}`,
      group: 'Navigate',
      icon: n.icon,
      shortcut: n.shortcut ? shortcut(n.shortcut) : undefined,
      onRun: () => navigate(n.to),
    }))
    const creates: (CommandAction & { feature?: FeatureId; local?: boolean })[] = [
      { id: 'new-chat', label: 'New chat', group: 'Create', icon: <MessageSquareText />, onRun: () => navigate('/chat') },
      { id: 'new-image', label: 'Generate an image', group: 'Create', icon: <Image />, feature: 'image', onRun: () => navigate('/image') },
      { id: 'new-speech', label: 'Text to speech', group: 'Create', icon: <AudioLines />, feature: 'voice', onRun: () => navigate('/voice/speak') },
      { id: 'clone-voice', label: 'Clone a voice', group: 'Create', icon: <AudioLines />, feature: 'voice', local: true, onRun: () => navigate('/voice/library') },
      { id: 'new-song', label: 'Compose a song', group: 'Create', icon: <Music />, feature: 'music', onRun: () => navigate('/music') },
      { id: 'new-video', label: 'Make a video', group: 'Create', icon: <Clapperboard />, feature: 'video', onRun: () => navigate('/video') },
      { id: 'browse-models', label: 'Browse model catalog', group: 'Create', icon: <Boxes />, keywords: ['download', 'install'], onRun: () => navigate('/models?tab=catalog') },
    ]
    const create: CommandAction[] = creates
      .filter((c) => !blocked(caps, c.feature, c.local))
      .map(({ feature: _feature, local: _local, ...action }) => action)
    const chats: CommandAction[] = (sessions ?? []).slice(0, 12).map((c) => ({
      id: `chat-${c.id}`,
      label: c.title || 'Untitled chat',
      group: 'Chats',
      icon: <MessageSquareText />,
      onRun: () => navigate(`/chat/${c.id}`),
    }))
    const adventures: CommandAction[] = blocked(caps, 'game')
      ? []
      : (games ?? []).slice(0, 12).map((g) => ({
          id: `game-${g.id}`,
          label: g.title,
          group: 'Adventures',
          icon: <Swords />,
          onRun: () => navigate(`/game/${g.id}`),
        }))
    const prefs: CommandAction[] = [
      { id: 'theme', label: `Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`, group: 'Preferences', icon: theme === 'dark' ? <Sun /> : <Moon />, onRun: () => setTheme(theme === 'dark' ? 'light' : 'dark') },
      { id: 'sidebar', label: 'Toggle sidebar', group: 'Preferences', icon: <PanelLeft />, shortcut: shortcut('B'), onRun: toggleSidebar },
    ]
    return [...create, ...nav, ...chats, ...adventures, ...prefs]
  }, [caps, pages, navigate, sessions, games, theme, setTheme, toggleSidebar])
}

/** The mark and the name. The mark beats its wings now and then, and keeps at it while the pointer is over it. */
function Brand({ collapsed }: { collapsed: boolean }) {
  const [hover, setHover] = useState(false)
  return (
    <div className={s.brand} onPointerEnter={() => setHover(true)} onPointerLeave={() => setHover(false)}>
      <span className={s.logo}>
        <Logo size={collapsed ? 36 : 42} mode={hover ? 'working' : 'alive'} glow />
      </span>
      {!collapsed && (
        <span className={s.brandName}>
          <span className={s.brandMark}>GROM</span> AI Studio
        </span>
      )}
    </div>
  )
}
