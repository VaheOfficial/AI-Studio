import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import {
  AlarmClock,
  ArrowRight,
  Calculator,
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSnow,
  CloudSun,
  Download,
  FileText,
  Moon,
  Sun,
} from 'lucide-react'
import { Button, cn } from '@studio/ui'
import type { FileArtifact, TableData, ToolDisplay, WeatherDisplay } from '../../api/contracts/workspace'
import type { ToolCall } from '../../api/types'
import { useChatLightbox } from './lightbox'
import s from './WidgetBodies.module.css'

type Body<K extends ToolDisplay['kind']> = (props: { call: ToolCall; display: Extract<ToolDisplay, { kind: K }> }) => ReactNode

/* --------------------------------- python --------------------------------- */

export const PythonBody: Body<'python'> = ({ display }) => (
  <div className={s.block}>
    <pre className={cn(s.code, s.scroll)}>{display.code}</pre>
    {display.output && <pre className={cn(s.output, s.scroll)}>{display.output}</pre>}
    {display.error && <pre className={cn(s.output, s.error, s.scroll)}>{display.error}</pre>}
    {display.table && <Table table={display.table} />}
    {display.images.length > 0 && (
      <div className={s.charts}>
        {display.images.map((url) => (
          <button key={url} className={s.chart} onClick={() => useChatLightbox.getState().show(url, 'Chart')}>
            <img src={url} alt="Chart" loading="lazy" />
          </button>
        ))}
      </div>
    )}
    {display.files.length > 0 && <FileList files={display.files} />}
  </div>
)

function Table({ table }: { table: TableData }) {
  return (
    <div className={s.tableWrap}>
      <table className={s.table}>
        <thead>
          <tr>
            {table.columns.map((c, i) => (
              <th key={i}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((r, i) => (
            <tr key={i}>
              {r.map((v, j) => (
                <td key={j}>{v}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {table.total_rows > table.rows.length && (
        <span className={s.meta}>
          First {table.rows.length} of {table.total_rows.toLocaleString()} rows
        </span>
      )}
    </div>
  )
}

const size = (n: number) =>
  n >= 2 ** 20 ? `${(n / 2 ** 20).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`

/** Files a tool made, each with a download button (Word, Excel, PowerPoint, PDF, CSV, …). */
export function FileList({ files }: { files: FileArtifact[] }) {
  return (
    <ul className={s.files}>
      {files.map((f) => (
        <li key={f.path} className={s.file}>
          <FileText size={16} className={s.fileIcon} />
          <span className={s.fileName} title={f.path}>
            {f.name}
          </span>
          <span className={s.meta}>{size(f.size)}</span>
          {f.url && (
            <Button size="sm" variant="secondary" iconLeft={<Download />} onClick={() => window.open(f.url, '_blank')}>
              Download
            </Button>
          )}
        </li>
      ))}
    </ul>
  )
}

/* --------------------------------- weather -------------------------------- */

function WeatherIcon({ code, day = true, size: px = 18 }: { code: number; day?: boolean; size?: number }) {
  if (code === 0) return day ? <Sun size={px} /> : <Moon size={px} />
  if (code <= 2) return <CloudSun size={px} />
  if (code === 3) return <Cloud size={px} />
  if (code === 45 || code === 48) return <CloudFog size={px} />
  if (code >= 51 && code <= 57) return <CloudDrizzle size={px} />
  if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return <CloudRain size={px} />
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return <CloudSnow size={px} />
  if (code >= 95) return <CloudLightning size={px} />
  return <Cloud size={px} />
}

const weekday = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short' })

export const WeatherBody: Body<'weather'> = ({ display: w }: { display: WeatherDisplay }) => {
  const deg = w.units === 'metric' ? '°C' : '°F'
  const speed = w.units === 'metric' ? 'km/h' : 'mph'
  return (
    <div className={cn(s.card, s.weather)}>
      <div className={s.weatherNow}>
        <span className={s.weatherIcon}>
          <WeatherIcon code={w.code} day={w.is_day} size={34} />
        </span>
        <div>
          <div className={s.big}>
            {Math.round(w.temp)}
            {deg}
          </div>
          <div className={s.sub}>{w.summary}</div>
        </div>
        <div className={s.weatherMeta}>
          <strong>{w.location}</strong>
          <span>
            Feels {Math.round(w.feels_like)}
            {deg} · Humidity {w.humidity}% · Wind {Math.round(w.wind)} {speed}
          </span>
        </div>
      </div>
      <div className={s.days}>
        {w.days.map((d) => (
          <div key={d.date} className={s.day} title={d.summary}>
            <span className={s.meta}>{weekday(d.date)}</span>
            <WeatherIcon code={d.code} />
            <span>
              {Math.round(d.t_max)}° <span className={s.min}>{Math.round(d.t_min)}°</span>
            </span>
            {d.precip_chance != null && <span className={s.rain}>{d.precip_chance}%</span>}
          </div>
        ))}
      </div>
      <span className={s.meta}>Source: {w.source}</span>
    </div>
  )
}

/* ---------------------------- calculator / units ---------------------------- */

export const CalcBody: Body<'calc'> = ({ display }) => (
  <div className={cn(s.card, s.calc)}>
    <Calculator size={18} className={s.cardIcon} />
    <span className={s.expr}>{display.expression}</span>
    <span className={s.eq}>=</span>
    <span className={s.big}>{display.result}</span>
  </div>
)

// 42.1648 km, 0.000125 kg: four decimals, more only for small numbers
const num = (n: number) =>
  Math.abs(n) >= 1 || n === 0
    ? n.toLocaleString(undefined, { maximumFractionDigits: 4 })
    : n.toLocaleString(undefined, { maximumSignificantDigits: 4 })

export const ConversionBody: Body<'conversion'> = ({ display }) => (
  <div className={s.card}>
    <div className={s.calc}>
      <span className={s.expr}>
        {num(display.value)} {display.from_unit}
      </span>
      <ArrowRight size={16} className={s.cardIcon} />
      <span className={s.big}>
        {num(display.result)} {display.to_unit}
      </span>
    </div>
    <span className={s.meta}>
      {display.category}
      {display.note && ` · ${display.note}`}
    </span>
  </div>
)

/* --------------------------------- clocks --------------------------------- */

function useNow() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

export const ClockBody: Body<'clock'> = ({ display }) => {
  const now = useNow()
  return (
    <div className={s.clocks}>
      {display.clocks.map((c) => {
        let time = ''
        let date = ''
        try {
          time = now.toLocaleTimeString(undefined, { timeZone: c.timezone, hour: '2-digit', minute: '2-digit', second: '2-digit' })
          date = now.toLocaleDateString(undefined, { timeZone: c.timezone, weekday: 'short', month: 'short', day: 'numeric' })
        } catch {
          time = '—'
        }
        return (
          <div key={`${c.location}${c.timezone}`} className={s.card}>
            <span className={s.meta}>{c.location}</span>
            <span className={s.big}>{time}</span>
            <span className={s.sub}>
              {date} · {c.timezone}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/* ------------------------------- automations ------------------------------- */

export const AutomationBody: Body<'automation'> = ({ display }) => {
  const navigate = useNavigate()
  return (
    <div className={cn(s.card, s.automation)}>
      <AlarmClock size={18} className={s.cardIcon} />
      <div className={s.automationText}>
        <strong>{display.title}</strong>
        <span className={s.sub}>
          {display.schedule}
          {display.next_run && ` · next ${new Date(display.next_run).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}`}
        </span>
      </div>
      <Button size="sm" variant="ghost" onClick={() => navigate('/automations')}>
        Manage
      </Button>
    </div>
  )
}
