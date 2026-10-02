import { useMemo } from 'react'
import { Masonry } from '@studio/ui'
import type { Job, Output } from '../../api/types'
import { Developing } from '../../components/Developing'
import { OutputView } from '../../components/OutputView'

/** A tile of the results: an image, or the place of one that is being made. */
interface Tile {
  id: string
  shape: number
  output?: Output
  pending?: number
}

const shapeOf = (t: Tile) => t.shape
const idOf = (t: Tile) => t.id

export interface ResultTilesProps {
  outputs: Output[]
  /** Images the running job is making; they hold their place at the front, in the shape they will have. */
  pending?: { count: number; width: number; height: number; job?: Job; preview?: string }
  onOpen: (o: Output) => void
  onDelete: (o: Output) => void
}

/** Generated images packed by their own shapes, the ones in the making first. */
export function ResultTiles({ outputs, pending, onOpen, onDelete }: ResultTilesProps) {
  const count = pending?.count ?? 0
  const shape = pending ? pending.height / pending.width : 1
  const jobId = pending?.job?.id
  const tiles = useMemo<Tile[]>(
    () => [
      ...Array.from({ length: count }, (_, i) => ({ id: `pending-${jobId}-${i}`, shape, pending: i })),
      ...outputs.map((o) => ({ id: o.id, shape: o.width && o.height ? o.height / o.width : 1, output: o })),
    ],
    [outputs, count, shape, jobId],
  )
  return (
    <Masonry
      items={tiles}
      itemKey={idOf}
      aspect={shapeOf}
      minColumnWidth={250}
      gap={12}
      renderItem={(t) =>
        t.output ? (
          <OutputView output={t.output} onOpen={onOpen} onDelete={onDelete} />
        ) : (
          <Developing progress={pending?.job?.progress ?? -1} message={pending?.job?.message} preview={t.pending === 0 ? pending?.preview : undefined} />
        )
      }
    />
  )
}
