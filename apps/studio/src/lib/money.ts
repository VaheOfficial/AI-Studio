import type { CloudPrice, PriceUnit } from '../api/contracts/openrouter'

const usd = (options: Intl.NumberFormatOptions) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', ...options })
const cents = usd({ minimumFractionDigits: 2, maximumFractionDigits: 2 })
const subDollar = usd({ minimumFractionDigits: 2, maximumFractionDigits: 4 })
const tiny = usd({ maximumSignificantDigits: 2 })

/** "$12.34", "$0.065", "$0.00042": precise enough that per-request charges and per-token prices stay visible. */
export function formatUsd(amount: number): string {
  const abs = Math.abs(amount)
  if (amount === 0) return '$0'
  return abs >= 1 ? cents.format(amount) : abs >= 0.01 ? subDollar.format(amount) : tiny.format(amount)
}

/** Account balances are always shown to the cent. */
export const formatBalance = (usd: number) => cents.format(usd)

const UNIT: Record<PriceUnit, string> = {
  input_mtok: 'in /M',
  output_mtok: 'out /M',
  image: '/image',
  megapixel: '/MP',
  mchar: '/M chars',
  minute: '/min',
  request: '/req',
}

const UNIT_LONG: Record<PriceUnit, string> = {
  input_mtok: 'per 1M input tokens',
  output_mtok: 'per 1M output tokens',
  image: 'per generated image',
  megapixel: 'per output megapixel',
  mchar: 'per 1M characters of input',
  minute: 'per minute of audio',
  request: 'per request',
}

export const formatPrice = (p: CloudPrice) => `${formatUsd(p.usd)} ${UNIT[p.unit]}`
export const describePrice = (p: CloudPrice) => `${formatUsd(p.usd)} ${UNIT_LONG[p.unit]}`
