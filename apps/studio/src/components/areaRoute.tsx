import { Suspense, type ReactNode } from 'react'
import { Navigate, type RouteObject } from 'react-router'
import { AreaLayout, SectionFallback, type AreaProps } from './AreaLayout'

/** Route object for an area: `/base` redirects to the first section, `/base/:id` renders each one. */
export function areaRoute(props: AreaProps, errorElement: ReactNode): RouteObject {
  return {
    path: props.base,
    element: <AreaLayout {...props} />,
    errorElement,
    children: [
      { index: true, element: <Navigate to={props.sections[0].id} replace /> },
      ...props.sections.map((sec) => ({
        path: sec.id,
        element: (
          <Suspense fallback={<SectionFallback />}>
            <sec.component />
          </Suspense>
        ),
      })),
    ],
  }
}
