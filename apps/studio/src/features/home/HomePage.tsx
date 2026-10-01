import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { motion } from 'motion/react'
import { ArrowRight, ArrowUp, Boxes, Cpu, HardDrive, KeyRound, MemoryStick } from 'lucide-react'
import { AnimatedNumber, Aurora, Badge, Card, IconButton, ProgressRing, StatusDot } from '@studio/ui'
import { useCapabilities, useCatalog, useOutputs } from '../../api/hooks'
import { useLive } from '../../api/live'
import type { FeatureId, ModelKind } from '../../api/types'
import { blocked } from '../../lib/capabilities'
import { OutputView } from '../../components/OutputView'
import { formatBytes } from '../../lib/format'
import { KINDS } from '../../lib/kinds'
import s from './HomePage.module.css'

const MODES: { kind: ModelKind; title: string; blurb: string; feature?: FeatureId }[] = [
  { kind: 'text', title: 'Chat & Agent', blurb: 'Talk to a model, or let the agent do the work with its tools.' },
  { kind: 'image', title: 'Image', blurb: 'Text-to-image with FLUX, Qwen-Image, HunyuanImage and more.', feature: 'image' },
  { kind: 'voice', title: 'Voice', blurb: 'Speech, voice cloning and transcription.', feature: 'voice' },
  { kind: 'music', title: 'Music', blurb: 'Full songs with vocals from a style prompt and lyrics.', feature: 'music' },
  { kind: 'video', title: 'Video', blurb: 'Clips from a prompt or an image — LTX-2.5 adds sound.', feature: 'video' },
]

const ease = [0.16, 1, 0.3, 1] as const

function greeting() {
  const h = new Date().getHours()
  return h < 5 ? 'Up late' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export default function HomePage() {
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState('')
  const models = useLive((st) => st.models)
  const { data: outputs = [] } = useOutputs()
  const { data: caps } = useCapabilities()
  // Without an NVIDIA GPU the studio is the agent and whatever a cloud key adds; the page says so
  const local = !caps || caps.gpu === 'nvidia'
  const modes = MODES.filter((m) => !blocked(caps, m.feature))

  const go = () => {
    if (!prompt.trim()) return
    navigate('/chat', { state: { prompt: prompt.trim() } })
  }

  return (
    <div className={s.page}>
      <section className={s.hero}>
        <Aurora className={s.aurora} />
        <motion.div className={s.heroInner} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease }}>
          <Badge tone="accent" dot pulse>
            {local ? 'Everything runs on your machine' : `Your agent, on this ${caps.machine}`}
          </Badge>
          <h1 className={s.title}>
            {greeting()}. <span className="text-gradient">What are we making?</span>
          </h1>
          <form
            className={s.prompt}
            onSubmit={(e) => {
              e.preventDefault()
              go()
            }}
          >
            <input
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={
                local
                  ? 'Ask the agent — “set up voice cloning”, “generate a logo”, “which LLM fits my GPU?”'
                  : 'Ask the agent — “summarize this PDF”, “build a spreadsheet from this data”, “research a topic”'
              }
              aria-label="Ask the agent"
            />
            <IconButton type="submit" variant="primary" size="lg" label="Ask" icon={<ArrowUp />} disabled={!prompt.trim()} />
          </form>
        </motion.div>
      </section>

      <div className={s.body}>
        <section className={s.modes}>
          {modes.map((m, i) => {
            const meta = KINDS[m.kind]
            const count = models.filter((x) => x.kind === m.kind || (m.kind === 'voice' && x.kind === 'stt')).length
            return (
              <motion.div key={m.kind} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + i * 0.06, duration: 0.5, ease }}>
                <Link to={meta.route} className={s.modeLink}>
                  <Card spotlight interactive tint={meta.hue} className={s.mode} padding="lg">
                    <span className={s.modeIcon} style={{ ['--hue' as string]: meta.hue }}>
                      {meta.icon}
                    </span>
                    <h3 className={s.modeTitle}>{m.title}</h3>
                    <p className={s.modeBlurb}>{m.blurb}</p>
                    <div className={s.modeFoot}>
                      <span className={s.modeCount}>
                        {count ? `${count} model${count > 1 ? 's' : ''} ready` : m.feature && caps?.features[m.feature].cloud ? 'Cloud models' : 'No models yet'}
                      </span>
                      <ArrowRight size={16} className={s.modeArrow} />
                    </div>
                  </Card>
                </Link>
              </motion.div>
            )
          })}
        </section>

        <div className={s.split}>
          <SystemPanel />
          {local ? <FeaturedPanel /> : <ConnectPanel machine={caps.machine} />}
        </div>

        {outputs.length > 0 && (
          <section className={s.recent}>
            <div className={s.sectionHead}>
              <h2>Recent creations</h2>
            </div>
            {/* Images tile in a grid; audio reads better as a list of players */}
            <div className={s.recentGrid}>
              {outputs
                .filter((o) => o.kind === 'image')
                .slice(0, 6)
                .map((o) => (
                  <OutputView key={o.id} output={o} compact />
                ))}
            </div>
            <div className={s.recentAudio}>
              {outputs
                .filter((o) => o.kind !== 'image')
                .slice(0, 3)
                .map((o) => (
                  <OutputView key={o.id} output={o} />
                ))}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}

function SystemPanel() {
  const data = useLive((st) => st.system)
  const gpu = data?.gpus[0]
  return (
    <Card className={s.panel} padding="lg">
      <div className={s.sectionHead}>
        <h2>This machine</h2>
        {data && (
          <span className={s.ollama}>
            <StatusDot status={data.ollama.running ? 'active' : data.ollama.installed ? 'idle' : 'off'} />
            Ollama {data.ollama.running ? 'running' : data.ollama.installed ? 'stopped' : 'not installed'}
          </span>
        )}
      </div>
      {!data ? (
        <p className={s.muted}>Waiting for the server…</p>
      ) : (
        <div className={s.meters}>
          {gpu && (
            <Meter
              icon={<Cpu />}
              label={gpu.name.replace('NVIDIA GeForce ', '')}
              value={gpu.vram_used / gpu.vram_total}
              detail={`${formatBytes(gpu.vram_used)} / ${formatBytes(gpu.vram_total, 0)} VRAM`}
              extra={`${Math.round(gpu.util)}% util${gpu.temp_c ? ` · ${gpu.temp_c}°C` : ''}`}
            />
          )}
          <Meter icon={<MemoryStick />} label="Memory" value={data.ram_used / data.ram_total} detail={`${formatBytes(data.ram_used)} / ${formatBytes(data.ram_total, 0)}`} extra={`CPU ${Math.round(data.cpu_percent)}%`} />
          <Meter icon={<HardDrive />} label="Storage" value={-1} detail={`${formatBytes(data.disk_free, 0)} free`} extra={data.data_dir} />
        </div>
      )}
    </Card>
  )
}

function Meter({ icon, label, value, detail, extra }: { icon: ReactNode; label: string; value: number; detail: string; extra?: string }) {
  return (
    <div className={s.meter}>
      <ProgressRing value={value >= 0 ? value : 0} size={52} stroke={4}>
        {value >= 0 ? <AnimatedNumber value={value * 100} /> : <span className={s.meterIcon}>{icon}</span>}
      </ProgressRing>
      <div className={s.meterText}>
        <span className={s.meterLabel}>{label}</span>
        <span className={s.meterDetail}>{detail}</span>
        {extra && <span className={s.meterExtra}>{extra}</span>}
      </div>
    </div>
  )
}

/** In place of GPU model suggestions on a machine that has no GPU for them: where chat models come from here. */
function ConnectPanel({ machine }: { machine: string }) {
  return (
    <Card className={s.panel} padding="lg">
      <div className={s.sectionHead}>
        <h2>Models for this {machine}</h2>
        <Link to="/settings" className={s.link}>
          Settings <ArrowRight size={13} />
        </Link>
      </div>
      <p className={s.muted}>
        <KeyRound size={14} /> Connect an OpenAI-compatible endpoint or OpenRouter in Settings.
      </p>
      <p className={s.muted}>
        <Boxes size={14} /> Or run a model on this machine with Ollama, llama.cpp or LM Studio from the Models page.
      </p>
    </Card>
  )
}

function FeaturedPanel() {
  const { data: catalog = [] } = useCatalog()
  const featured = catalog.filter((c) => c.featured && !c.installed && c.fit !== 'no').slice(0, 4)
  return (
    <Card className={s.panel} padding="lg">
      <div className={s.sectionHead}>
        <h2>Suggested for your GPU</h2>
        <Link to="/models?tab=catalog" className={s.link}>
          Catalog <ArrowRight size={13} />
        </Link>
      </div>
      {featured.length === 0 ? (
        <p className={s.muted}>
          <Boxes size={14} /> You're all set — or the catalog hasn't loaded yet.
        </p>
      ) : (
        <div className={s.featured}>
          {featured.map((f) => (
            <Link key={f.id} to={`/models?tab=catalog&kind=${f.kind}`} className={s.featuredItem} style={{ ['--hue' as string]: KINDS[f.kind].hue }}>
              <span className={s.featuredIcon}>{KINDS[f.kind].icon}</span>
              <span className={s.featuredText}>
                <span className={s.featuredName}>{f.name}</span>
                <span className={s.featuredMeta}>
                  {f.vendor} · {f.size_gb.toFixed(f.size_gb < 10 ? 1 : 0)} GB
                </span>
              </span>
              <Badge size="sm" tone={f.fit === 'yes' ? 'success' : 'warning'}>
                {f.fit === 'yes' ? 'Fits' : 'Offload'}
              </Badge>
            </Link>
          ))}
        </div>
      )}
    </Card>
  )
}
