# React-Markdown Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-rolled custom markdown tokenizer with `react-markdown` + `remark-gfm` + `react-syntax-highlighter` (Prism/oneDark), matching the Virtua demo exactly.

**Architecture:** The `MarkdownRenderer` component keeps its existing `{ content, className }` prop interface — only its internals change. `MarkdownRendererLegacy` in `App.jsx` is dead code (never called) and gets deleted. No other files change.

**Tech Stack:** react-markdown, remark-gfm, react-syntax-highlighter (Prism + oneDark theme), Vite dev server for manual verification via Playwright.

---

## File Map

| File | Action |
|---|---|
| `frontend/src/components/ui/MarkdownRenderer.jsx` | **Rewrite** — gut custom tokenizer, replace with ReactMarkdown |
| `frontend/src/App.jsx` | **Edit** — delete the unused `MarkdownRendererLegacy` function (lines 339–395) |

No other files change. `MessageRow.jsx`, `App.jsx` import paths, and all CSS remain untouched.

---

### Task 1: Install the three new packages

**Files:**
- Modify: `frontend/package.json` (via npm)
- Modify: `frontend/package-lock.json` (via npm)

- [ ] **Step 1: Install packages**

```bash
cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
npm install react-markdown remark-gfm react-syntax-highlighter
```

Expected output: `added N packages` with no errors.

- [ ] **Step 2: Verify the build still compiles**

```bash
cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
npm run build 2>&1 | tail -10
```

Expected: build completes with `✓ built in` — no errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
git add package.json package-lock.json
git commit -m "chore: add react-markdown, remark-gfm, react-syntax-highlighter"
```

---

### Task 2: Rewrite MarkdownRenderer.jsx

**Files:**
- Modify: `frontend/src/components/ui/MarkdownRenderer.jsx`

- [ ] **Step 1: Replace the entire file with the new implementation**

Overwrite `frontend/src/components/ui/MarkdownRenderer.jsx` with exactly:

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
        <SyntaxHighlighter
          language={match[1]}
          style={oneDark}
          PreTag="div"
          customStyle={{ margin: 0, borderRadius: '0.5rem', padding: '0.75rem' }}
        >
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

- [ ] **Step 2: Verify the build compiles**

```bash
cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
npm run build 2>&1 | tail -10
```

Expected: `✓ built in` — no errors, no unresolved imports.

- [ ] **Step 3: Start the dev server and verify rendering in the browser**

Start the frontend dev server:
```bash
cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
npm run dev
```

Then use Playwright to navigate to `http://localhost:5173`, log in, send a chat message that contains markdown (e.g. `show me a list with **bold** text, a \`code\` block, and a table`). Take a screenshot and confirm:
- Headings render bold and large
- Bullet lists render with dots
- Inline code renders in a monospace style
- Fenced code blocks render with dark background (oneDark) and syntax highlighting
- GFM tables render with rows and columns

- [ ] **Step 4: Commit**

```bash
cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
git add src/components/ui/MarkdownRenderer.jsx
git commit -m "feat: replace custom MarkdownRenderer with react-markdown + remark-gfm + prism"
```

---

### Task 3: Delete MarkdownRendererLegacy from App.jsx

**Files:**
- Modify: `frontend/src/App.jsx`

`MarkdownRendererLegacy` (lines 339–395 of `App.jsx`) is defined but never called — it is dead code. Deleting it also removes the now-orphaned `CodeBlock`, `tokenizeCode`, `tokenizeJSON`, `KW`, and `parseInline` helpers defined only for its use.

> **Before deleting:** confirm `statusClass` (lines 331–336) is kept — it is used by `DataTable` and `ToolResult`. Only delete `MarkdownRendererLegacy` and the helpers listed below.

- [ ] **Step 1: Delete the MarkdownRendererLegacy function and its private helpers from App.jsx**

Delete these blocks from `frontend/src/App.jsx` (search by function name, delete their entire definitions):

1. `const KW = { ... }` — the keyword sets object (lines ~176–181)
2. `function tokenizeJSON(code) { ... }` — (lines ~183–208)
3. `function tokenizeCode(code, lang) { ... }` — (lines ~210–267)
4. `function CodeBlock({ code, lang }) { ... }` — (lines ~271–289)
5. `function parseInline(text, baseKey = 0) { ... }` — (lines ~294–329)
6. `function MarkdownRendererLegacy({ content, className = '' }) { ... }` — (lines ~339–395)

Keep `statusClass` (used by `DataTable` and `ToolResult`). Keep `MessageRowLegacy` untouched (separate concern, out of scope).

- [ ] **Step 2: Verify the build compiles with no errors**

```bash
cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
npm run build 2>&1 | tail -15
```

Expected: `✓ built in` — no "is not defined" errors.

If you see `tokenizeCode is not defined` or similar, you deleted too much or too little — check which functions `MessageRowLegacy` uses and restore only those.

- [ ] **Step 3: Verify the app still renders correctly**

Start the dev server (`npm run dev`). Use Playwright to navigate to the app, load a conversation with existing markdown messages, and take a screenshot. Confirm messages still render — no blank white boxes, no crash.

- [ ] **Step 4: Commit**

```bash
cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
git add src/App.jsx
git commit -m "chore: remove dead MarkdownRendererLegacy and its private helpers from App.jsx"
```
