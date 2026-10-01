import { useState } from 'react'
import { Link } from 'react-router'
import { Lock, LockOpen, Mic2, Save, Trash2 } from 'lucide-react'
import { AudioPlayer, Badge, Button, ConfirmDialog, Field, Input, Sheet, Textarea } from '@studio/ui'
import type { StagedReference, VoiceProfile } from '../../api/contracts/voice'
import { useDeleteProfile, useUnlockProfile, useUpdateProfile } from '../../api/voice'
import { AUTO_LANGUAGE, LanguagePicker } from './LanguagePicker'
import { ReferenceInput } from './ReferenceInput'
import { VoiceOrb } from './VoiceOrb'
import s from './ProfileEditor.module.css'

/** Side panel for one saved voice: rename, transcript, style, language, replace reference, lock, delete. */
export function ProfileEditor({ profile, onClose }: { profile: VoiceProfile | null; onClose: () => void }) {
  return (
    <Sheet
      open={!!profile}
      onOpenChange={(o) => !o && onClose()}
      title={profile?.name ?? ''}
      description={profile ? `${profile.kind === 'design' ? 'Designed' : 'Cloned'} voice` : undefined}
      icon={profile && <VoiceOrb seed={profile.id} size={30} />}
      size="md"
    >
      {profile && <EditorBody key={profile.id} profile={profile} onClose={onClose} />}
    </Sheet>
  )
}

function EditorBody({ profile, onClose }: { profile: VoiceProfile; onClose: () => void }) {
  const [name, setName] = useState(profile.name)
  const [refText, setRefText] = useState(profile.ref_text ?? '')
  const [instruct, setInstruct] = useState(profile.instruct ?? '')
  const [language, setLanguage] = useState(profile.language ?? AUTO_LANGUAGE)
  const [tags, setTags] = useState(profile.tags.join(', '))
  const [staged, setStaged] = useState<StagedReference | null>(null)
  const [replacing, setReplacing] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const update = useUpdateProfile()
  const unlock = useUnlockProfile()
  const del = useDeleteProfile()

  const save = () =>
    update.mutate(
      {
        id: profile.id,
        name: name.trim(),
        ref_text: refText.trim(),
        instruct: instruct.trim(),
        language: language === AUTO_LANGUAGE ? '' : language,
        tags: tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
        ref_id: staged?.id,
      },
      {
        onSuccess: () => {
          setStaged(null)
          setReplacing(false)
        },
      },
    )

  return (
    <div className={s.body}>
      <Field label="Name">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} />}</Field>

      <Field
        label="Reference clip"
        aside={
          <Button size="sm" variant="ghost" onClick={() => setReplacing((r) => !r)}>
            {replacing ? 'Keep current' : 'Replace'}
          </Button>
        }
      >
        {replacing ? (
          <ReferenceInput
            staged={staged}
            onStaged={(ref) => {
              setStaged(ref)
              setRefText(ref.text)
            }}
          />
        ) : profile.ref_audio_url ? (
          <AudioPlayer src={profile.ref_audio_url} color="var(--hue-voice)" height={36} />
        ) : (
          <span className={s.muted}>No reference clip.</span>
        )}
      </Field>

      <Field label="Transcript" hint="What the reference clip says, word for word. Left empty, it is transcribed on first use.">
        {(id) => <Textarea id={id} autoResize minRows={2} maxRows={8} value={refText} onChange={(e) => setRefText(e.target.value)} />}
      </Field>

      <Field label={profile.kind === 'design' ? 'Design tags' : 'Style tags'} hint="Comma-separated OmniVoice tags, e.g. “female, elderly, whisper”.">
        {(id) => <Input id={id} value={instruct} onChange={(e) => setInstruct(e.target.value)} />}
      </Field>

      <div className={s.pair}>
        <Field label="Language">{(id) => <LanguagePicker id={id} value={language} onChange={setLanguage} engine="omnivoice" />}</Field>
        <Field label="Tags">{(id) => <Input id={id} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="warm, narrator" />}</Field>
      </div>

      <Field label="Lock">
        {profile.is_locked ? (
          <div className={s.locked}>
            <Badge tone="success" icon={<Lock />}>
              Locked{profile.seed !== undefined ? ` · seed ${profile.seed}` : ''}
            </Badge>
            {profile.locked_audio_url && <AudioPlayer src={profile.locked_audio_url} color="var(--hue-voice)" compact height={28} bars={48} />}
            <Button size="sm" variant="ghost" iconLeft={<LockOpen />} loading={unlock.isPending} onClick={() => unlock.mutate(profile.id)}>
              Unlock
            </Button>
          </div>
        ) : (
          <span className={s.muted}>
            Not locked. In <Link to={`/voice/speak?voice=${encodeURIComponent(profile.id)}`}>Speak</Link>, lock a take you like to make this voice
            render reproducibly.
          </span>
        )}
      </Field>

      <div className={s.actions}>
        <Button variant="danger" iconLeft={<Trash2 />} onClick={() => setConfirm(true)}>
          Delete
        </Button>
        <Link to={`/voice/speak?voice=${encodeURIComponent(profile.id)}`} className={s.speak}>
          <Button variant="ghost" iconLeft={<Mic2 />}>
            Speak
          </Button>
        </Link>
        <Button variant="primary" iconLeft={<Save />} loading={update.isPending} disabled={!name.trim() || (replacing && !staged)} onClick={save}>
          Save changes
        </Button>
      </div>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        tone="danger"
        title={`Delete “${profile.name}”?`}
        description="Its reference clip and locked take are removed. Takes already rendered stay in the history."
        confirmLabel="Delete"
        onConfirm={() => del.mutateAsync(profile.id).then(onClose)}
      />
    </div>
  )
}
