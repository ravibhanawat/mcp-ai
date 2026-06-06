# Replace MarkdownRenderer with react-markdown

**Date:** 2026-06-07
**Status:** Approved

## Problem

The app ships a hand-rolled `MarkdownRenderer` (~220 lines) with a custom tokenizer for ABAP, SQL, JavaScript, Python, and JSON. It has several known gaps: no spec-compliant inline parsing, no GFM checkbox support, limited language coverage for syntax highlighting, and crashes on `null` content (just patched). Maintaining a bespoke parser is ongoing cost with no benefit over established libraries.

## Goal

Replace the custom renderer with `react-markdown` + `remark-gfm` + `react-syntax-highlighter` (Prism), matching the pattern shown in the Virtua markdown demo. Keep the external interface (`content`, `className` props) identical so no call sites change.

## Packages to Add

| Package | Purpose |
|---|---|
| `react-markdown` | Spec-compliant markdown → React tree |
| `remark-gfm` | GFM tables, strikethrough, task lists, autolinks |
| `react-syntax-highlighter` | Prism-based code block highlighting (oneDark theme) |

## What Changes

### `frontend/src/components/ui/MarkdownRenderer.jsx`

Gut the custom tokenizer and replace with:

```jsx
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

const components = {
  code({ className, children }) {
    const match = /language-(\w+)/.exec(className || '')
    if (match) {
      return (
        <SyntaxHighlighter language={match[1]} style={oneDark} PreTag="div"
          customStyle={{ margin: 0, borderRadius: '0.5rem', padding: '0.75rem' }}>
          {String(children).replace(/\n$/, '')}
        </SyntaxHighlighter>
      )
    }
    return <code className={className}>{children}</code>
  },
}

export default function MarkdownRenderer({ content, className = '' }) {
  if (!content) return <div className={`md-body ${className}`} />
  return (
    <div className={`md-body ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
```

No copy button (intentionally dropped for simplicity).

### `frontend/src/App.jsx`

- Delete `MarkdownRendererLegacy` (~55 lines, lines 339–394).
- Add `import MarkdownRenderer from './components/ui/MarkdownRenderer.jsx'` at the top.
- Update `ResearchReport` (one line) to call `<MarkdownRenderer>` instead of `<MarkdownRendererLegacy>`.

### No other files change

`MessageRow.jsx` and every other call site already import from `../ui/MarkdownRenderer.jsx` — no changes needed.

## What Stays the Same

- Prop interface: `{ content, className }`
- Null guard: returns empty `div` when content is falsy
- Wrapper `div` with `md-body` class (existing CSS applies)
- All existing CSS rules for `md-body`, `md-table`, headings, etc. continue to work via markdown's standard HTML output

## Out of Scope

- No changes to VList / Virtualizer setup
- No changes to chat store or streaming logic
- No new UI features (no copy button, no theme switcher)
