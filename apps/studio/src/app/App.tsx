import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter } from 'react-router'
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
const ChatPage = lazy(() => import('../features/chat/ChatPage'))
const GamePage = lazy(() => import('../features/game/GamePage'))
const ModelsPage = lazy(() => import('../features/models/ModelsPage'))
const SettingsPage = lazy(() => import('../features/settings/SettingsPage'))
const LogsPage = lazy(() => import('../features/logs/LogsPage'))
const AutomationsPage = lazy(() => import('../features/automations/AutomationsPage'))

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
          { path: 'chat', element: page(<ChatPage />) },
          { path: 'chat/:sessionId', element: page(<ChatPage />) },
          { path: 'game', element: page(<GamePage />) },
          { path: 'game/:gameId', element: page(<GamePage />) },
          areaRoute(IMAGE_AREA, <RouteError />),
          areaRoute(VOICE_AREA, <RouteError />),
          areaRoute(MUSIC_AREA, <RouteError />),
          areaRoute(VIDEO_AREA, <RouteError />),
          { path: 'models', element: page(<ModelsPage />) },
          { path: 'automations', element: page(<AutomationsPage />) },
          { path: 'settings', element: page(<SettingsPage />) },
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
      <TooltipProvider>
        <RouterProvider router={router} />
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  )
}
