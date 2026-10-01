import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useMatch, useNavigate, useOutlet } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import { AlarmClock, AudioLines, Boxes, Clapperboard, House, Image, MessageSquareText, Moon, MoreHorizontal, Music, PanelLeft, Pencil, Plus, ScrollText, Search, Settings, Sun, Swords, Trash2 } from 'lucide-react'
import { CommandPalette, ConfirmDialog, IconButton, Kbd, Menu, StatusDot, Tooltip, cn, type CommandAction } from '@studio/ui'
import { useCapabilities, useDeleteSession, useSessions, useUpdateSession } from '../api/hooks'
import type { AgentSession, FeatureId } from '../api/types'
import { useLive, useRealtime } from '../api/live'
import { CreditPill } from '../features/openrouter/CreditPill'
import { blocked } from '../lib/capabilities'
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
}

const NAV: NavItem[] = [
  { to: '/', label: 'Home', icon: <House />, shortcut: '1' },
  { to: '/chat', label: 'Chat', icon: <MessageSquareText />, hue: 'var(--hue-text)', shortcut: '2' },
  { to: '/image', label: 'Image', icon: <Image />, hue: 'var(--hue-image)', shortcut: '3', feature: 'image' },
  { to: '/voice', label: 'Voice', icon: <AudioLines />, hue: 'var(--hue-voice)', shortcut: '4', feature: 'voice' },
  { to: '/music', label: 'Music', icon: <Music />, hue: 'var(--hue-music)', shortcut: '5', feature: 'music' },
  { to: '/video', label: 'Video', icon: <Clapperboard />, hue: 'var(--hue-video)', shortcut: '8', feature: 'video' },
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

  return (
    <div className={cn(s.shell, sidebarCollapsed && s.collapsed)}>
      <aside className={s.sidebar}>
        <div className={s.brand}>
          <Logo />
          {!sidebarCollapsed && (
            <span className={s.brandName}>
              AI <span className="text-gradient">Studio</span>
            </span>
          )}
        </div>

        <button className={s.search} onClick={() => setCommandOpen(true)}>
          <Search size={15} />
          {!sidebarCollapsed && (
            <>
              <span>Search or run…</span>
              <Kbd>{shortcut('K')}</Kbd>
            </>
          )}
        </button>

        <nav className={s.nav} aria-label="Main">
          {nav.map((item) => (
            <SideLink key={item.to} item={item} collapsed={sidebarCollapsed} />
          ))}
        </nav>

        {!sidebarCollapsed && <RecentChats />}

        <div className={s.sidebarFooter}>
          {FOOTER_NAV.map((item) => (
            <SideLink key={item.to} item={item} collapsed={sidebarCollapsed} />
          ))}
          <GpuMeter collapsed={sidebarCollapsed} />
        </div>
      </aside>

      <div className={s.main}>
        <header className={s.topbar}>
          <IconButton label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'} icon={<PanelLeft />} onClick={toggleSidebar} tooltipSide="bottom" />
          <div className={s.topbarSpacer} />
          <CreditPill />
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

function SideLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  // Plain className/children (not NavLink's render functions): the collapsed rail's Tooltip trigger merges props
  // as strings and would turn a className function into garbage, leaving the link unstyled.
  const isActive = !!useMatch({ path: item.to, end: item.to === '/' })
  const link = (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={cn(s.navItem, isActive && s.navActive)}
      style={item.hue ? { ['--hue' as string]: item.hue } : undefined}
    >
      {isActive && <motion.span layoutId="nav-active" className={s.navPill} transition={{ type: 'spring', stiffness: 500, damping: 40 }} />}
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
    const prefs: CommandAction[] = [
      { id: 'theme', label: `Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`, group: 'Preferences', icon: theme === 'dark' ? <Sun /> : <Moon />, onRun: () => setTheme(theme === 'dark' ? 'light' : 'dark') },
      { id: 'sidebar', label: 'Toggle sidebar', group: 'Preferences', icon: <PanelLeft />, shortcut: shortcut('B'), onRun: toggleSidebar },
    ]
    return [...create, ...nav, ...chats, ...prefs]
  }, [caps, pages, navigate, sessions, theme, setTheme, toggleSidebar])
}

function Logo() {
  return (
    <svg className={s.logo} viewBox="0 0 32 32" aria-hidden>
      <defs>
        <linearGradient id="logo-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a78bfa" />
          <stop offset="0.5" stopColor="#818cf8" />
          <stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="var(--bg-3)" />
      <path d="M16 5.5 18.6 13.4 26.5 16 18.6 18.6 16 26.5 13.4 18.6 5.5 16 13.4 13.4Z" fill="url(#logo-g)" />
    </svg>
  )
}
