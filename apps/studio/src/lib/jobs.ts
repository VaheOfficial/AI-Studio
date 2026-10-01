import type { Job } from '../api/types'

export const isActive = (j: Job) => j.status === 'queued' || j.status === 'running'
