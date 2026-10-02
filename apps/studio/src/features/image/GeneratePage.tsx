import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { ArrowRight, Image as ImageIcon, Sparkles, Wand2 } from 'lucide-react'
import { Button, EmptyState, Field, GridBackdrop, Kbd, Suggestions, Textarea } from '@studio/ui'
import { useDeleteOutput, useOutputs } from '../../api/hooks'
import { useGenerateImage, useImagePreview, useStars, useToggleStar } from '../../api/image'
import { useJob } from '../../api/live'
import type { Output } from '../../api/types'
import { StudioHead, StudioLayout } from '../../components/Page'
import { PAGE_KEY, buildRequest, useImageDraft, useImageHandoff, useTakeHandoff } from './draft'
import { ImageDetail } from './ImageDetail'
import { ImageModelPicker } from './ImageModelPicker'
import { ImageSettings } from './ImageSettings'
import { useImageModelChoice } from './modelChoice'
import { ResultTiles } from './ResultTiles'
import s from './Studio.module.css'

// Starting points for an empty canvas
const IDEAS = [
  'A lighthouse on a basalt cliff at blue hour, volumetric fog, 35mm film grain',
  'Isometric cutaway of a tiny workshop, warm lamps, clay render',
  'Macro photo of a dew-covered spider web at sunrise, shallow depth of field',
  'Vintage travel poster of a mountain railway, bold flat colors',
]

const RECENT = 48

export default function GeneratePage() {
  const navigate = useNavigate()
  const handed = useTakeHandoff('generate')
  const choice = useImageModelChoice(PAGE_KEY.generate, (p) => p.modes.includes('txt2img'), 'image')
  const { profile } = choice
  const { draft, patch, reuse } = useImageDraft(profile, handed)
  const [jobId, setJobId] = useState<string>()
  const [viewing, setViewing] = useState<Output | null>(null)
  const [pending, setPending] = useState(1)

  const generate = useGenerateImage()
  const job = useJob(jobId)
  const preview = useImagePreview(jobId)
  const running = job && (job.status === 'queued' || job.status === 'running')
  const { data: outputs = [] } = useOutputs('image')
  const recent = outputs.slice(0, RECENT)
  const del = useDeleteOutput()
  const { data: stars = [] } = useStars()
  const star = useToggleStar()
  const sendHandoff = useImageHandoff((st) => st.send)

  const submit = () => {
    if (!profile || !draft.prompt.trim() || running) return
    const { req, seed } = buildRequest(draft, profile, 'txt2img')
    if (!draft.lockSeed) patch({ lastSeed: seed })
    setPending(req.count)
    generate.mutate(req, { onSuccess: (j) => setJobId(j.id) })
  }

  const reuseHere = (o: Output) => {
    const known = choice.models.some((m) => m.id === o.model_id)
    if (known) choice.select(o.model_id)
    reuse(o, known ? o.model_id : undefined)
    setViewing(null)
  }

  const controls = (
    <form
      className={s.form}
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <StudioHead icon={<ImageIcon />} title="Generate" subtitle="Text to image" />

      <ImageModelPicker {...choice} onSelect={choice.select} />

      <Field label="Prompt" aside={`${draft.prompt.length}`}>
        {(id) => (
          <Textarea
            id={id}
            autoResize
            minRows={5}
            maxRows={14}
            value={draft.prompt}
            onChange={(e) => patch({ prompt: e.target.value })}
            placeholder="A lighthouse on a basalt cliff at blue hour, volumetric fog, 35mm film grain…"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                submit()
              }
            }}
          />
        )}
      </Field>

      {profile && <ImageSettings profile={profile} draft={draft} patch={patch} />}

      <div className={s.submit}>
        <Button
          type="submit"
          variant="glow"
          size="lg"
          block
          iconLeft={<Sparkles />}
          loading={generate.isPending || !!running}
          disabled={!profile || !draft.prompt.trim()}
        >
          {running ? 'Generating…' : 'Generate'}
        </Button>
        <span className={s.hint}>
          <Kbd>Ctrl</Kbd> <Kbd>Enter</Kbd>
          {profile?.cost && <span className={s.cost}>{profile.cost}</span>}
        </span>
      </div>
    </form>
  )


  return (
    <StudioLayout controls={controls} hue="var(--hue-image)">
      <GridBackdrop />
      <div className={s.canvas}>
        {recent.length === 0 && !running ? (
          <EmptyState
            size="lg"
            backdrop
            tint="var(--hue-image)"
            icon={<Wand2 />}
            title="Your canvas is empty"
            description="Describe an image on the left, or start from one of these. Results land here and in the Gallery."
          >
            <Suggestions items={IDEAS} icon={<Sparkles />} onPick={(prompt) => patch({ prompt })} />
          </EmptyState>
        ) : (
          <>
            <ResultTiles
              outputs={recent}
              pending={running ? { count: pending, width: draft.width, height: draft.height, job, preview: preview?.image } : undefined}
              onOpen={setViewing}
              onDelete={(x) => del.mutate(x.id)}
            />
            {outputs.length > RECENT && (
              <div className={s.more}>
                <Button asChild variant="ghost" iconRight={<ArrowRight />}>
                  <Link to="/image/gallery">All {outputs.length} images in the Gallery</Link>
                </Button>
              </div>
            )}
          </>
        )}
      </div>

      <ImageDetail
        output={viewing}
        onClose={() => setViewing(null)}
        onReuse={reuseHere}
        onEdit={(o) => {
          sendHandoff('edit', o)
          navigate('/image/edit')
        }}
        onDelete={(o) => del.mutate(o.id)}
        starred={!!viewing && stars.includes(viewing.id)}
        onStar={(o, starred) => star.mutate({ id: o.id, starred })}
      />
    </StudioLayout>
  )
}
