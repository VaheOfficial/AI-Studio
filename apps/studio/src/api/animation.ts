import { api } from './client'
import type { AnimationCatalog, AnimationComposition, AnimationRenderRequest, AnimationValidation } from './contracts/animation'
import type { Job } from './types'

export const animationCatalog = () => api.get<AnimationCatalog>('/animation/catalog')
export const animationRecipe = (key: string) => api.get<AnimationComposition>(`/animation/recipes/${encodeURIComponent(key)}`)
export const validateAnimation = (composition: AnimationComposition) => api.post<AnimationValidation>('/animation/validate', composition)
export const renderAnimation = (request: AnimationRenderRequest) => api.post<Job>('/animation/render', request)
