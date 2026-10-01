import type { ReactNode } from 'react'
import s from './Providers.module.css'

/** Chrome shared by every provider sub-card in Settings → Providers. */
export function ProviderCard({ icon, name, description, status, children }: { icon: ReactNode; name: string; description: string; status?: ReactNode; children: ReactNode }) {
  return (
    <section className={s.card} aria-label={name}>
      <div className={s.head}>
        <span className={s.icon}>{icon}</span>
        <div className={s.titles}>
          <h3 className={s.name}>{name}</h3>
          <p className={s.desc}>{description}</p>
        </div>
        {status}
      </div>
      <div className={s.body}>{children}</div>
    </section>
  )
}
