import { memo, useState } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, Copy } from 'lucide-react'
import { useChatLightbox } from './lightbox'
import { splitWriting } from './writing'
import { WritingBlock } from './WritingBlock'
import s from './Markdown.module.css'

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className={s.codeBlock}>
      <div className={s.codeHead}>
        <span>{lang || 'text'}</span>
        <button
          className={s.copy}
          onClick={() => {
            void navigator.clipboard.writeText(code)
            setCopied(true)
            setTimeout(() => setCopied(false), 1400)
          }}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  )
}

const components: Components = {
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children }) => {
    const text = String(children ?? '')
    const lang = /language-(\w+)/.exec(className ?? '')?.[1]
    // Fenced blocks have a language class or contain newlines; everything else is inline
    if (lang || text.includes('\n')) return <CodeBlock lang={lang ?? ''} code={text.replace(/\n$/, '')} />
    return <code className={s.inline}>{children}</code>
  },
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
  img: ({ src, alt }) =>
    typeof src === 'string' ? (
      <img className={s.img} src={src} alt={alt ?? ''} loading="lazy" onClick={() => useChatLightbox.getState().show(src, alt)} />
    ) : null,
}

const renderMarkdown = (text: string) => (
  <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
    {text}
  </ReactMarkdown>
)

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  const segments = splitWriting(text)
  return (
    <div className={s.md}>
      {segments.map((seg, i) =>
        seg.kind === 'writing' ? (
          <WritingBlock key={`w${seg.block.id}${i}`} block={seg.block} render={renderMarkdown} />
        ) : (
          <ReactMarkdown key={i} remarkPlugins={[remarkGfm]} components={components}>
            {seg.text}
          </ReactMarkdown>
        ),
      )}
    </div>
  )
})
