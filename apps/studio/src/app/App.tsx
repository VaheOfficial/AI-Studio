import { lazy, Suspense, useEffect, type ReactNode } from 'react'
import { createBrowserRouter, Navigate, useNavigate, useParams } from 'react-router'
import { MotionConfig } from 'motion/react'
import { RouterProvider } from 'react-router/dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Loader, Toaster, TooltipProvider } from '@studio/ui'
import { ApiError } from '../api/client'
import { areaRoute } from '../components/areaRoute'
import { IMAGE_AREA } from '../features/image/sections'
import { MUSIC_AREA } from '../features/music/sections'
import { VIDEO_AREA } from '../features/video/sections'
import { VOICE_AREA } from '../features/voice/sections'
import { RouteError } from './RouteError'
import { Shell } from './Shell'

const HomePage = lazy(() => import('../features/home/HomePage'))
const GamePage = lazy(() => import('../features/game/GamePage'))
const GamesPage = lazy(() => import('../features/games/GamesPage'))
const ArenaPage = lazy(() => import('../features/games/ArenaPage'))
const ModelsPage = lazy(() => import('../features/models/ModelsPage'))
import { openSettings } from '../features/settings/settingsState'
const LogsPage = lazy(() => import('../features/logs/LogsPage'))
const AutomationsPage = lazy(() => import('../features/automations/AutomationsPage'))
const AgentsPage = lazy(() => import('../features/agents/AgentsPage'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: false,
      // Don't hammer a server that isn't running (the WebSocket reconnect refreshes everything), and don't repeat
      // requests the server refused (4xx: not found, invalid) — they won't succeed on a second try
      retry: (count, err) =>
        !(err instanceof ApiError && (err.status === 0 || (err.status >= 400 && err.status < 500))) && count < 2,
    },
  },
})

// Dev-only handle for inspecting the cache from the console
if (import.meta.env.DEV) Object.assign(window, { __studioQueryClient: queryClient })

const page = (el: ReactNode) => <Suspense fallback={<PageFallback />}>{el}</Suspense>

const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      {
        // Pathless layout route so a crashing page is contained inside the shell
        errorElement: <RouteError />,
        children: [
          { index: true, element: page(<HomePage />) },
          { path: 'agents', element: page(<AgentsPage />) },
          { path: 'agents/:section', element: page(<AgentsPage />) },
          { path: 'agents/chat/:sessionId', element: page(<AgentsPage />) },
          { path: 'agents/missions/:sessionId', element: page(<AgentsPage />) },
          { path: 'agents/legacy/:swarmId', element: page(<AgentsPage />) },
          { path: 'chat', element: <Navigate to="/agents/chat" replace /> },
          { path: 'chat/:sessionId', element: <LegacyAgentRoute section="chat" /> },
          { path: 'agent-plus', element: <Navigate to="/agents/missions" replace /> },
          { path: 'agent-plus/:sessionId', element: <LegacyAgentRoute section="missions" /> },
          { path: 'games', element: page(<GamesPage />) },
          { path: 'games/arena', element: page(<ArenaPage />) },
          { path: 'games/arena/:arenaId', element: page(<ArenaPage />) },
          { path: 'games/adventures', element: page(<GamePage />) },
          { path: 'games/adventures/:gameId', element: page(<GamePage />) },
          { path: 'game', element: <Navigate to="/games/adventures" replace /> },
          { path: 'game/:gameId', element: <LegacyGameRoute /> },
          areaRoute(IMAGE_AREA, <RouteError />),
          areaRoute(VOICE_AREA, <RouteError />),
          areaRoute(MUSIC_AREA, <RouteError />),
          areaRoute(VIDEO_AREA, <RouteError />),
          { path: 'models', element: page(<ModelsPage />) },
          { path: 'automations', element: page(<AutomationsPage />) },
          { path: 'swarm', element: <Navigate to="/agents/activity" replace /> },
          { path: 'swarm/:swarmId', element: <LegacyAgentRoute section="legacy" /> },
          { path: 'settings', element: <SettingsRoute /> },
          { path: 'logs', element: page(<LogsPage />) },
          { path: '*', element: <RouteError /> },
        ],
      },
    ],
  },
])

function PageFallback() {
  return (
    <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}>
      <Loader size={150} />
    </div>
  )
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="user"><TooltipProvider>
        <RouterProvider router={router} />
        <Toaster />
      </TooltipProvider></MotionConfig>
    </QueryClientProvider>
  )
}

function LegacyAgentRoute({ section }: { section: string }) {
  const { sessionId, swarmId } = useParams()
  return <Navigate replace to={`/agents/${section}/${sessionId ?? swarmId}`} />
}

function LegacyGameRoute() {
  const { gameId } = useParams()
  return <Navigate replace to={`/games/adventures/${gameId}`} />
}

function SettingsRoute() {
  const navigate = useNavigate()
  useEffect(() => { openSettings(); navigate('/agents/chat', { replace: true }) }, [navigate])
  return null
}
