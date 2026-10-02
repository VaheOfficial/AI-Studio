import { useRef, useState, type DragEvent } from 'react'
import { Brush, Eraser, FlipHorizontal2, ImagePlus, PencilLine, Plus, RefreshCw, Sparkles, Trash2, X } from 'lucide-react'
import {
  Button,
  EmptyState,
  Field,
  GridBackdrop,
  IconButton,
  Kbd,
  MaskCanvas,
  SegmentedControl,
  Slider,
  Textarea,
  toast,
  type MaskCanvasHandle,
} from '@studio/ui'
import type { ImageMode } from '../../api/contracts/image'
import { useDeleteOutput, useOutputs } from '../../api/hooks'
import { useGenerateImage, useImagePreview, useStars, useToggleStar } from '../../api/image'
import { useJob } from '../../api/live'
import type { Output } from '../../api/types'
import { StudioHead, StudioLayout } from '../../components/Page'
import { PAGE_KEY, buildRequest, useImageDraft, useTakeHandoff } from './draft'
import { ImageDetail } from './ImageDetail'
import { ImageModelPicker } from './ImageModelPicker'
import { ImageSettings } from './ImageSettings'
import { useImageModelChoice } from './modelChoice'
import { ResultTiles } from './ResultTiles'
import { sizeForRatio } from './sizes'
import s from './Studio.module.css'
import e from './EditPage.module.css'

type EditMode = Exclude<ImageMode, 'txt2img'>

const MODES: { value: EditMode; label: string; hint: string }[] = [
  { value: 'img2img', label: 'Restyle', hint: 'Redraw the whole image guided by the prompt; strength sets how far it may move.' },
  { value: 'inpaint', label: 'Inpaint', hint: 'Paint over the part to change; everything else is kept.' },
  { value: 'edit', label: 'Instruct', hint: 'Describe the change ("make it night", "add a red scarf"); the model reads the image itself.' },
]
const EDIT_MODES = new Set<ImageMode>(['img2img', 'inpaint', 'edit'])

interface Source {
  url: string // data URL (upload) or /files/outputs/... (a generated image)
  width: number
  height: number
}

function readImage(file: File): Promise<Source> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`))
    reader.onload = () => {
      const url = String(reader.result)
      const img = new Image()
      img.onload = () => resolve({ url, width: img.naturalWidth, height: img.naturalHeight })
      img.onerror = () => reject(new Error(`${file.name} is not an image the browser can open`))
      img.src = url
    }
    reader.readAsDataURL(file)
  })
}

const fromOutput = (o: Output): Source => ({ url: o.url, width: o.width ?? 1024, height: o.height ?? 1024 })

export default function EditPage() {
  const handed = useTakeHandoff('edit')
  const choice = useImageModelChoice(PAGE_KEY.edit, (p) => p.modes.some((m) => EDIT_MODES.has(m)), 'image_edit')
  const { profile } = choice
  const { draft, patch, reuse } = useImageDraft(profile, handed)
  const [source, setSource] = useState<Source | null>(() => (handed ? fromOutput(handed) : null))
  const [references, setReferences] = useState<Source[]>([])
  const [modePick, setModePick] = useState<EditMode>('img2img')
  const [mask, setMask] = useState<string | null>(null)
  const [brush, setBrush] = useState(40)
  const [tool, setTool] = useState<'paint' | 'erase'>('paint')
  const [jobId, setJobId] = useState<string>()
  const [pending, setPending] = useState(1)
  const [viewing, setViewing] = useState<Output | null>(null)
  const maskRef = useRef<MaskCanvasHandle>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const refFileRef = useRef<HTMLInputElement>(null)

  const modes = MODES.filter((m) => profile?.modes.includes(m.value))
  const mode = modes.some((m) => m.value === modePick) ? modePick : (modes[0]?.value ?? 'img2img')
  const size = profile && source ? sizeForRatio(source.width / source.height, profile) : undefined

  const generate = useGenerateImage()
  const job = useJob(jobId)
  const preview = useImagePreview(jobId)
  const running = job && (job.status === 'queued' || job.status === 'running')
  const { data: outputs = [] } = useOutputs('image')
  const edits = outputs.filter((o) => EDIT_MODES.has((o.params as { mode?: ImageMode }).mode ?? 'txt2img')).slice(0, 36)
  const del = useDeleteOutput()
  const { data: stars = [] } = useStars()
  const star = useToggleStar()

  const pickSource = async (file: File | undefined) => {
    if (!file) return
    try {
      setSource(await readImage(file))
      setMask(null)
    } catch (err) {
      toast.error('Could not open image', (err as Error).message)
    }
  }

  const addReference = async (file: File | undefined) => {
    if (!file) return
    try {
      const ref = await readImage(file)
      setReferences((r) => [...r, ref])
    } catch (err) {
      toast.error('Could not open image', (err as Error).message)
    }
  }

  const onDrop = (ev: DragEvent) => {
    ev.preventDefault()
    void pickSource(ev.dataTransfer.files[0])
  }

  const maxRefs = Math.max(0, (profile?.max_images ?? 1) - 1)
  const canSubmit = !!profile && !!source && !!draft.prompt.trim() && (mode !== 'inpaint' || !!mask)

  const submit = () => {
    if (!profile || !source || !size || !canSubmit || running) return
    const images = [source.url, ...(mode === 'edit' ? references.slice(0, maxRefs).map((r) => r.url) : [])]
    const { req, seed } = buildRequest({ ...draft, width: size.w, height: size.h }, profile, mode, {
      images,
      mask: mode === 'inpaint' ? (mask ?? undefined) : undefined,
    })
    if (!draft.lockSeed) patch({ lastSeed: seed })
    setPending(req.count)
    generate.mutate(req, { onSuccess: (j) => setJobId(j.id) })
  }

  const controls = (
    <form
      className={s.form}
      onSubmit={(ev) => {
        ev.preventDefault()
        submit()
      }}
    >
      <StudioHead icon={<PencilLine />} title="Edit" subtitle="Restyle, inpaint, instruct" />

      <ImageModelPicker {...choice} onSelect={choice.select} />

      {modes.length > 1 && (
        <Field label="Mode" hint={modes.find((m) => m.value === mode)?.hint}>
          <SegmentedControl block value={mode} onValueChange={setModePick} segments={modes.map((m) => ({ value: m.value, label: m.label }))} />
        </Field>
      )}

      <Field label={mode === 'edit' ? 'Instruction' : 'Prompt'} aside={`${draft.prompt.length}`}>
        {(id) => (
          <Textarea
            id={id}
            autoResize
            minRows={3}
            maxRows={10}
            value={draft.prompt}
            onChange={(ev) => patch({ prompt: ev.target.value })}
            placeholder={mode === 'edit' ? 'Turn it into a watercolor painting at dusk' : 'What the result should look like'}
            onKeyDown={(ev) => {
              if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) {
                ev.preventDefault()
                submit()
              }
            }}
          />
        )}
      </Field>

      {(mode === 'img2img' || mode === 'inpaint') && (
        <Field label="Strength" aside={draft.strength.toFixed(2)} hint="Low keeps the original, high reimagines it">
          <Slider aria-label="Strength" value={draft.strength} onValueChange={(v) => patch({ strength: v })} min={0.05} max={1} step={0.01} />
        </Field>
      )}

      {mode === 'inpaint' && (
        <Field label="Brush" aside={`${brush}px`}>
          <div className={e.brushRow}>
            <SegmentedControl
              size="sm"
              value={tool}
              onValueChange={setTool}
              segments={[
                { value: 'paint', label: 'Paint', icon: <Brush size={13} /> },
                { value: 'erase', label: 'Erase', icon: <Eraser size={13} /> },
              ]}
            />
            <Slider aria-label="Brush size" value={brush} onValueChange={setBrush} min={4} max={200} className={e.brushSlider} />
          </div>
        </Field>
      )}

      {mode === 'edit' && maxRefs > 0 && (
        <Field label="Extra references" aside={`${references.length}/${maxRefs}`} hint="Other images the instruction can refer to">
          <div className={e.refs}>
            {references.map((r, i) => (
              <div key={r.url.slice(-32) + i} className={e.ref}>
                <img src={r.url} alt="" />
                <IconButton size="sm" label="Remove" icon={<X />} onClick={() => setReferences((x) => x.filter((_, j) => j !== i))} />
              </div>
            ))}
            {references.length < maxRefs && (
              <button type="button" className={e.addRef} onClick={() => refFileRef.current?.click()} aria-label="Add reference image">
                <Plus />
              </button>
            )}
          </div>
        </Field>
      )}

      {profile && <ImageSettings profile={profile} draft={size ? { ...draft, width: size.w, height: size.h } : draft} patch={patch} lockedRatio={source ? source.width / source.height : undefined} />}

      <div className={s.submit}>
        <Button type="submit" variant="glow" size="lg" block iconLeft={<Sparkles />} loading={generate.isPending || !!running} disabled={!canSubmit}>
          {running ? 'Working…' : !source ? 'Add an image first' : mode === 'inpaint' && !mask ? 'Paint a mask first' : 'Apply edit'}
        </Button>
        <span className={s.hint}>
          <Kbd>Ctrl</Kbd> <Kbd>Enter</Kbd>
          {profile?.cost && <span className={s.cost}>{profile.cost}</span>}
        </span>
      </div>
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={(ev) => void pickSource(ev.target.files?.[0])} />
      <input ref={refFileRef} type="file" accept="image/*" hidden onChange={(ev) => void addReference(ev.target.files?.[0])} />
    </form>
  )

  return (
    <StudioLayout controls={controls} hue="var(--hue-image)">
      <GridBackdrop />
      <div className={s.canvas}>
        {!source ? (
          <div className={e.drop} onDragOver={(ev) => ev.preventDefault()} onDrop={onDrop}>
            <EmptyState
              tint="var(--hue-image)"
              icon={<ImagePlus />}
              title="Start from an image"
              description="Drop an image here, upload one, or pick a recent result below."
              action={
                <Button variant="secondary" iconLeft={<ImagePlus />} onClick={() => fileRef.current?.click()}>
                  Upload image
                </Button>
              }
            />
            {outputs.length > 0 && (
              <div className={e.recent}>
                {outputs.slice(0, 12).map((o) => (
                  <button key={o.id} type="button" className={e.pick} onClick={() => setSource(fromOutput(o))} title={o.prompt}>
                    <img src={o.url} alt={o.prompt} loading="lazy" />
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className={e.stage}>
            <div className={e.toolbar}>
              <span className={e.dims}>
                Source {source.width}×{source.height}
                {size && ` → ${size.w}×${size.h}`}
              </span>
              {mode === 'inpaint' && (
                <>
                  <Button size="sm" variant="ghost" iconLeft={<FlipHorizontal2 />} onClick={() => maskRef.current?.invert()}>
                    Invert mask
                  </Button>
                  <Button size="sm" variant="ghost" iconLeft={<Trash2 />} onClick={() => maskRef.current?.clear()} disabled={!mask}>
                    Clear mask
                  </Button>
                </>
              )}
              <Button size="sm" variant="ghost" iconLeft={<RefreshCw />} onClick={() => fileRef.current?.click()}>
                Replace
              </Button>
              <IconButton
                size="sm"
                label="Remove image"
                icon={<X />}
                onClick={() => {
                  setSource(null)
                  setMask(null)
                }}
              />
            </div>
            <div className={e.source} onDragOver={(ev) => ev.preventDefault()} onDrop={onDrop}>
              {mode === 'inpaint' ? (
                <MaskCanvas key={source.url} ref={maskRef} src={source.url} brush={brush} tool={tool} onChange={setMask} />
              ) : (
                <img className={e.sourceImg} src={source.url} alt="Source" />
              )}
            </div>
          </div>
        )}

        {(edits.length > 0 || running) && (
          <section className={e.results}>
            <h2 className={e.resultsTitle}>Recent edits</h2>
            <ResultTiles
              outputs={edits}
              pending={running ? { count: pending, width: size?.w ?? 1, height: size?.h ?? 1, job, preview: preview?.image } : undefined}
              onOpen={setViewing}
              onDelete={(x) => del.mutate(x.id)}
            />
          </section>
        )}
      </div>

      <ImageDetail
        output={viewing}
        onClose={() => setViewing(null)}
        onReuse={(o) => {
          reuse(o)
          setViewing(null)
        }}
        onEdit={(o) => {
          setSource(fromOutput(o))
          setMask(null)
          setViewing(null)
        }}
        onDelete={(o) => del.mutate(o.id)}
        starred={!!viewing && stars.includes(viewing.id)}
        onStar={(o, starred) => star.mutate({ id: o.id, starred })}
      />
    </StudioLayout>
  )
}
