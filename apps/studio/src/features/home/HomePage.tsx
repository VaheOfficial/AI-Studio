import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { motion } from 'motion/react'
import { ArrowRight, ArrowUp, Boxes, Cpu, HardDrive, KeyRound, MemoryStick, MessageSquareText, Plus } from 'lucide-react'
import { AnimatedNumber, Aurora, Badge, Card, CircuitField, IconButton, Logo, ProgressRing, ScrambleText, SignalWave, StatusDot, cn } from '@studio/ui'
import { useCapabilities, useCatalog, useOutputs, useSessions } from '../../api/hooks'
import { useLive } from '../../api/live'
import type { FeatureId, Output } from '../../api/types'
import { blocked } from '../../lib/capabilities'
import { launchedUnderSplash, useLanded } from '../../lib/desktop'
import { OutputView } from '../../components/OutputView'
import { formatBytes, timeAgo } from '../../lib/format'
import { KINDS } from '../../lib/kinds'
import s from './HomePage.module.css'

type Area = 'text' | 'image' | 'voice' | 'music' | 'video'

const AREAS: Record<Area, { title: string; blurb: string; feature?: FeatureId }> = {
  text: { title: 'Chat & Agent', blurb: 'Talk to a model, or let the agent do the work with its tools.' },
  image: { title: 'Image', blurb: 'Text-to-image with FLUX, Qwen-Image, HunyuanImage and more.', feature: 'image' },
  voice: { title: 'Voice', blurb: 'Speech, voice cloning and transcription.', feature: 'voice' },
  music: { title: 'Music', blurb: 'Full songs with vocals from a style prompt and lyrics.', feature: 'music' },
  video: { title: 'Video', blurb: 'Clips from a prompt or an image — LTX-2.5 adds sound.', feature: 'video' },
}

// What the agent can be asked from an empty chat list
const STARTERS = ['Which of my models fits this task best?', 'Summarize a document for me', 'Plan and write a small script']

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
  const has = (area: Area) => !blocked(caps, AREAS[area].feature)
  const strips = (['voice', 'music', 'video'] as const).filter(has)
  const visuals = outputs.filter((o) => o.kind === 'image' || o.kind === 'video').slice(0, 9)
  const sounds = outputs.filter((o) => o.kind === 'audio' || o.kind === 'music').slice(0, 2)
  const recent = visuals.length > 0 || sounds.length > 0
  /** What an area has to work with: its installed models, or cloud ones. */
  const ready = (area: Area) => {
    const count = models.filter((x) => x.kind === area || (area === 'voice' && x.kind === 'stt')).length
    const feature = AREAS[area].feature
    return count ? `${count} model${count > 1 ? 's' : ''} ready` : feature && caps?.features[feature].cloud ? 'Cloud models' : 'No models yet'
  }

  // The mark builds itself when the page opens, then settles into its resting wing beats. Under the desktop
  // app's splash screen it is already built: the splash sets its own mark down on this one.
  const [built, setBuilt] = useState(launchedUnderSplash)
  const landed = useLanded()
  useEffect(() => {
    if (built) return
    const done = setTimeout(() => setBuilt(true), 2100)
    return () => clearTimeout(done)
  }, [built])

  const go = () => {
    if (!prompt.trim()) return
    navigate('/chat', { state: { prompt: prompt.trim() } })
  }

  return (
    <div className={s.page}>
      <section className={s.hero}>
        <Aurora className={s.aurora} />
        <CircuitField className={s.circuit} />
        <motion.div className={s.heroInner} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease }}>
          <span className={s.mark} data-launch-mark style={landed ? undefined : { visibility: 'hidden' }}>
            <Logo size={148} mode={built ? 'alive' : 'assemble'} glow />
          </span>
          <Badge tone="accent" dot pulse>
            {local ? 'Everything runs on your machine' : `Your agent, on this ${caps.machine}`}
          </Badge>
          <h1 className={s.title}>
            <ScrambleText text={`${greeting()}.`} />{' '}
            <motion.span
              className={`text-gradient ${s.titleAccent}`}
              initial={{ clipPath: 'inset(0 100% 0 0)', opacity: 0 }}
              animate={{ clipPath: 'inset(0 0% 0 0)', opacity: 1 }}
              transition={{ delay: 0.5, duration: 0.95, ease }}
            >
              What are we making?
            </motion.span>
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

      <div className={s.bento}>
        <Tile index={0} className={cn(s.chat, !has('image') && s.chatWide)}>
          <ChatTile ready={ready('text')} />
        </Tile>
        {has('image') && (
          <Tile index={1} className={s.image}>
            <ImageTile ready={ready('image')} images={outputs.filter((o) => o.kind === 'image').slice(0, 3)} />
          </Tile>
        )}
        <Tile index={2} className={s.machine}>
          <SystemPanel />
        </Tile>
        {strips.length > 0 && (
          <div className={s.strips}>
            {strips.map((area, i) => (
              <Tile key={area} index={3 + i}>
                <StripTile area={area} ready={ready(area)} />
              </Tile>
            ))}
          </div>
        )}
        {recent && (
          <Tile index={6} className={s.recent}>
            <RecentTile visuals={visuals} sounds={sounds} />
          </Tile>
        )}
        <Tile index={7} className={cn(s.side, !recent && s.sideWide)}>
          {local ? <FeaturedPanel /> : <ConnectPanel machine={caps.machine} />}
        </Tile>
      </div>
    </div>
  )
}

/** A cell of the page's grid; its content rises into place a beat after the one before it. */
function Tile({ index, className, children }: { index: number; className?: string; children: ReactNode }) {
  // Behind the desktop app's splash screen the tiles wait, and rise as the page is torn into view
  const landed = useLanded()
  return (
    <motion.div
      className={cn(s.tile, className)}
      initial={{ opacity: 0, y: 16 }}
      animate={landed ? { opacity: 1, y: 0 } : { opacity: 0, y: 16 }}
      transition={{ delay: 0.08 + index * 0.05, duration: 0.55, ease }}
    >
      {children}
    </motion.div>
  )
}

function TileHead({ area, ready }: { area: Area; ready: string }) {
  const meta = KINDS[area]
  return (
    <div className={s.tileHead}>
      <span className={s.tileIcon}>{meta.icon}</span>
      <div className={s.tileTitles}>
        <h3 className={s.tileTitle}>{AREAS[area].title}</h3>
        <span className={s.tileReady}>{ready}</span>
      </div>
      <ArrowRight size={16} className={s.tileArrow} />
    </div>
  )
}

const hueOf = (area: Area) => ({ ['--hue' as string]: KINDS[area].hue }) as CSSProperties

/** Chat: the latest conversations to pick up again, or a few things to ask when there are none. */
function ChatTile({ ready }: { ready: string }) {
  const navigate = useNavigate()
  const { data: sessions = [] } = useSessions()
  return (
    <Card spotlight tint={KINDS.text.hue} padding="none" className={s.card} style={hueOf('text')}>
      <Link to="/chat" className={s.headLink}>
        <TileHead area="text" ready={ready} />
      </Link>
      <p className={s.blurb}>{AREAS.text.blurb}</p>
      <div className={s.rows}>
        {sessions.length > 0
          ? sessions.slice(0, 3).map((c) => (
              <Link key={c.id} to={`/chat/${c.id}`} className={s.row}>
                <MessageSquareText />
                <span className={s.rowText}>{c.title || 'Untitled'}</span>
                <span className={s.rowMeta}>{timeAgo(c.updated_at)}</span>
              </Link>
            ))
          : STARTERS.map((prompt) => (
              <button key={prompt} type="button" className={s.row} onClick={() => navigate('/chat', { state: { prompt } })}>
                <Plus />
                <span className={s.rowText}>{prompt}</span>
              </button>
            ))}
      </div>
    </Card>
  )
}

/** Image: the latest pictures fanned out like prints on a table (blank ones until there are any). */
function ImageTile({ ready, images }: { ready: string; images: Output[] }) {
  return (
    <Link to="/image" className={s.cardLink}>
      <Card spotlight interactive tint={KINDS.image.hue} padding="none" className={s.card} style={hueOf('image')}>
        <TileHead area="image" ready={ready} />
        <p className={s.blurb}>{AREAS.image.blurb}</p>
        <div className={s.fan} aria-hidden>
          {[0, 1, 2].map((i) => {
            const image = images[i]
            return (
              <span key={i} className={s.print} data-i={i}>
                {image && <img src={image.url} alt="" loading="lazy" />}
              </span>
            )
          })}
        </div>
      </Card>
    </Link>
  )
}

/** Voice, Music, Video: a low, wide tile each, with a moving figure of what the area makes. */
function StripTile({ area, ready }: { area: 'voice' | 'music' | 'video'; ready: string }) {
  return (
    <Link to={KINDS[area].route} className={s.cardLink}>
      <Card spotlight interactive tilt tint={KINDS[area].hue} padding="none" className={cn(s.card, s.strip)} style={hueOf(area)}>
        <TileHead area={area} ready={ready} />
        <p className={s.blurb}>{AREAS[area].blurb}</p>
        <div className={s.figure} aria-hidden>
          {area === 'voice' && <SignalWave className={s.wave} level={0.8} />}
          {area === 'music' && (
            <span className={s.bars}>
              {Array.from({ length: 22 }, (_, i) => (
                <i key={i} style={{ ['--n' as string]: i }} />
              ))}
            </span>
          )}
          {area === 'video' && (
            <span className={s.film}>
              {Array.from({ length: 8 }, (_, i) => (
                <i key={i} />
              ))}
            </span>
          )}
        </div>
      </Card>
    </Link>
  )
}

/** The latest pictures and clips as rows of one height and their own widths; sounds as players under them. */
function RecentTile({ visuals, sounds }: { visuals: Output[]; sounds: Output[] }) {
  return (
    <Card padding="none" className={s.card}>
      <div className={s.sectionHead}>
        <h2>Recent creations</h2>
        <Link to="/image/gallery" className={s.link}>
          Gallery <ArrowRight size={13} />
        </Link>
      </div>
      {visuals.length > 0 && (
        <div className={s.mosaic}>
          {visuals.map((o) => {
            const ratio = o.width && o.height ? o.width / o.height : 1
            return (
              <Link
                key={o.id}
                to={o.kind === 'video' ? '/video' : '/image/gallery'}
                className={s.shot}
                style={{ ['--ratio' as string]: ratio }}
                title={o.prompt}
              >
                {o.kind === 'video' ? <video src={o.url} muted loop playsInline preload="metadata" /> : <img src={o.url} alt={o.prompt} loading="lazy" />}
              </Link>
            )
          })}
        </div>
      )}
      {sounds.length > 0 && (
        <div className={s.sounds}>
          {sounds.map((o) => (
            <OutputView key={o.id} output={o} />
          ))}
        </div>
      )}
    </Card>
  )
}

function SystemPanel() {
  const data = useLive((st) => st.system)
  const gpu = data?.gpus[0]
  return (
    <Card className={cn(s.card, s.panel)} padding="none">
      <div className={s.sectionHead}>
        <h2>This machine</h2>
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
      {data && (
        <span className={s.ollama}>
          <StatusDot status={data.ollama.running ? 'active' : data.ollama.installed ? 'idle' : 'off'} />
          Ollama {data.ollama.running ? 'running' : data.ollama.installed ? 'stopped' : 'not installed'}
        </span>
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
    <Card className={cn(s.card, s.panel)} padding="none">
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
    <Card className={cn(s.card, s.panel)} padding="none">
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
