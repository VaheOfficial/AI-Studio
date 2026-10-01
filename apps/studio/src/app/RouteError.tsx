import { isRouteErrorResponse, useNavigate, useRouteError } from 'react-router'
import { RotateCcw, TriangleAlert } from 'lucide-react'
import { Button, EmptyState } from '@studio/ui'

/** Rendered in place of a page that threw, keeping the shell (sidebar, jobs) alive. */
export function RouteError() {
  const error = useRouteError()
  const navigate = useNavigate()
  // Also used for the catch-all route, where there is no error — just an unknown URL
  const notFound = error == null || (isRouteErrorResponse(error) && error.status === 404)
  const message = notFound
    ? 'There is nothing at this address.'
    : isRouteErrorResponse(error)
      ? `${error.status} ${error.statusText}`
      : error instanceof Error
        ? error.message
        : String(error)

  return (
    <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}>
      <EmptyState
        tint={notFound ? 'var(--accent)' : 'var(--danger)'}
        icon={<TriangleAlert />}
        title={notFound ? 'Page not found' : 'This page hit an error'}
        description={message}
        action={
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="ghost" onClick={() => navigate('/')}>
              Go home
            </Button>
            <Button variant="primary" iconLeft={<RotateCcw />} onClick={() => window.location.reload()}>
              Reload
            </Button>
          </div>
        }
      />
    </div>
  )
}
