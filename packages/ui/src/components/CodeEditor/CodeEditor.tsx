import { useEffect, useRef } from 'react'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { css } from '@codemirror/lang-css'
import { html } from '@codemirror/lang-html'
import { javascript } from '@codemirror/lang-javascript'
import { json } from '@codemirror/lang-json'
import { markdown } from '@codemirror/lang-markdown'
import { python } from '@codemirror/lang-python'
import { bracketMatching, HighlightStyle, indentOnInput, syntaxHighlighting } from '@codemirror/language'
import { Annotation, Compartment, EditorState, type Extension } from '@codemirror/state'
import {
  drawSelection,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
} from '@codemirror/view'
import { tags as t } from '@lezer/highlight'
import { cn } from '../../lib/cn'
import s from './CodeEditor.module.css'

export interface CodeEditorProps {
  value: string
  /** Picks the syntax mode from the extension (js/ts/jsx/tsx, py, json, css, html, md). */
  filename?: string
  readOnly?: boolean
  onChange?: (value: string) => void
  /** Ctrl/Cmd+S. */
  onSave?: () => void
  /** Soft-wrap long lines (default on). */
  wrap?: boolean
  className?: string
}

function languageFor(filename = ''): Extension {
  const ext = filename.toLowerCase().split('.').pop() ?? ''
  if (['js', 'mjs', 'cjs', 'jsx'].includes(ext)) return javascript({ jsx: true })
  if (['ts', 'mts', 'cts', 'tsx'].includes(ext)) return javascript({ jsx: ext === 'tsx', typescript: true })
  if (ext === 'py') return python()
  if (ext === 'json') return json()
  if (['css', 'scss'].includes(ext)) return css()
  if (['html', 'htm', 'svg', 'xml'].includes(ext)) return html()
  if (['md', 'markdown'].includes(ext)) return markdown()
  return []
}

/** Marks document replacements coming from the `value` prop (not user edits). */
const external = Annotation.define<boolean>()

/** Syntax colors from the modality/status tokens, so both themes work. */
const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.operatorKeyword, t.modifier], color: 'var(--hue-text)' },
  { tag: [t.string, t.special(t.string), t.regexp], color: 'var(--success)' },
  { tag: [t.number, t.bool, t.null, t.atom], color: 'var(--hue-image)' },
  { tag: [t.comment, t.lineComment, t.blockComment], color: 'var(--text-3)', fontStyle: 'italic' },
  { tag: [t.function(t.variableName), t.function(t.propertyName)], color: 'var(--info)' },
  { tag: [t.typeName, t.className, t.namespace], color: 'var(--hue-voice)' },
  { tag: [t.propertyName, t.attributeName], color: 'var(--hue-stt)' },
  { tag: [t.tagName, t.heading], color: 'var(--hue-music)', fontWeight: '600' },
  { tag: t.link, color: 'var(--accent-text)', textDecoration: 'underline' },
  { tag: t.invalid, color: 'var(--danger)' },
])

const theme = EditorView.theme({
  '&': { height: '100%', color: 'var(--text-1)', backgroundColor: 'var(--bg-0)', fontSize: '12.5px' },
  '.cm-scroller': { fontFamily: 'var(--font-mono)', lineHeight: '1.6' },
  '.cm-content': { caretColor: 'var(--accent-text)' },
  '.cm-gutters': { backgroundColor: 'var(--bg-0)', color: 'var(--text-4)', border: 'none' },
  '.cm-activeLine': { backgroundColor: 'var(--surface)' },
  '.cm-activeLineGutter': { backgroundColor: 'var(--surface)', color: 'var(--text-2)' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground': { backgroundColor: 'var(--accent-soft)' },
  '.cm-cursor': { borderLeftColor: 'var(--accent-text)' },
  '&.cm-focused': { outline: 'none' },
  '.cm-matchingBracket': { backgroundColor: 'var(--surface-active)', outline: '1px solid var(--border-strong)' },
})

/** CodeMirror 6 editor/viewer. Controlled: external `value` changes replace the document. */
export function CodeEditor({ value, filename, readOnly, onChange, onSave, wrap = true, className }: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const handlers = useRef({ onChange, onSave })
  const compartments = useRef({ lang: new Compartment(), ro: new Compartment(), wrap: new Compartment() })
  useEffect(() => {
    handlers.current = { onChange, onSave }
  })

  useEffect(() => {
    const el = host.current
    if (!el) return
    const { lang, ro, wrap: wrapping } = compartments.current
    const v = new EditorView({
      parent: el,
      state: EditorState.create({
        doc: '',
        extensions: [
          lineNumbers(),
          highlightActiveLineGutter(),
          highlightActiveLine(),
          drawSelection(),
          history(),
          indentOnInput(),
          bracketMatching(),
          syntaxHighlighting(highlight),
          keymap.of([
            {
              key: 'Mod-s',
              preventDefault: true,
              run: () => {
                handlers.current.onSave?.()
                return true
              },
            },
            indentWithTab,
            ...defaultKeymap,
            ...historyKeymap,
          ]),
          theme,
          lang.of([]),
          ro.of([]),
          wrapping.of([]),
          EditorView.updateListener.of((u) => {
            if (u.docChanged && !u.transactions.some((tr) => tr.annotation(external))) {
              handlers.current.onChange?.(u.state.doc.toString())
            }
          }),
        ],
      }),
    })
    view.current = v
    return () => {
      v.destroy()
      view.current = null
    }
  }, [])

  useEffect(() => {
    view.current?.dispatch({ effects: compartments.current.lang.reconfigure(languageFor(filename)) })
  }, [filename])

  useEffect(() => {
    view.current?.dispatch({
      effects: compartments.current.ro.reconfigure(readOnly ? [EditorState.readOnly.of(true), EditorView.editable.of(false)] : []),
    })
  }, [readOnly])

  useEffect(() => {
    view.current?.dispatch({ effects: compartments.current.wrap.reconfigure(wrap ? EditorView.lineWrapping : []) })
  }, [wrap])

  useEffect(() => {
    const v = view.current
    if (!v || v.state.doc.toString() === value) return
    v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value }, annotations: external.of(true) })
  }, [value])

  return <div ref={host} className={cn(s.editor, className)} />
}
