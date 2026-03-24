# SAP AI Agent — Reusable Component Library

> **Policy:** No external UI libraries. Every component is built from scratch using React + CSS custom properties. Zero runtime dependencies beyond `react` and `react-dom`.

---

## Design System

All design tokens live in `src/index.css` as CSS custom properties.

### Color Tokens

| Token | Value | Usage |
|---|---|---|
| `--sb-bg` | `#09090b` | Sidebar background (dark) |
| `--tb-bg` | `#09090b` | Topbar background |
| `--bg` | `#fafafa` | Main content background |
| `--bg-card` | `#ffffff` | Card / panel backgrounds |
| `--accent` | `#0070D2` | SAP Blue — primary actions |
| `--purple` | `#7c3aed` | Research mode |
| `--border` | `#e4e4e7` | Default border |
| `--text-primary` | `#18181b` | Body text |
| `--text-secondary` | `#71717a` | Labels, secondary text |
| `--text-muted` | `#a1a1aa` | Placeholders, hints |

### Typography

```css
--font-sans: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', 'Menlo', monospace;
```

### Radius

```css
--r-sm: 4px   /* tags, tiny chips */
--r:    6px   /* buttons, badges */
--r-md: 8px   /* form inputs, cards */
--r-lg: 10px  /* panels, dropdowns */
--r-xl: 12px  /* modals */
--r-2xl:16px  /* large cards, login */
--r-full: 9999px  /* pills */
```

### Shadows

```css
--shadow-xs  /* subtle card lift */
--shadow-sm  /* elevated cards */
--shadow-md  /* dropdowns */
--shadow-lg  /* popovers */
--shadow-xl  /* modals */
```

### Transitions

```css
--t:      150ms ease   /* default micro-interaction */
--t-slow: 250ms ease   /* entrance animations */
```

---

## Components

### `Icons`

Zero-dependency SVG icon library. All icons are inline SVG with `stroke="currentColor"`.

```jsx
// Usage — all icons are in the Icons object
<Icons.grid />
<Icons.dollar />
<Icons.settings />
<Icons.logout />
<Icons.send />
<Icons.trash />
<Icons.beaker />     // Research mode
<Icons.terminal />   // Tool badge
<Icons.refresh />
<Icons.copy />
<Icons.alert />
<Icons.check />
<Icons.chevDown />
<Icons.chevUp />
<Icons.x />          // Close button
<Icons.wifi />
<Icons.wifiOff />
<Icons.panel />      // Sidebar toggle
```

**Available icons:**
`grid`, `dollar`, `package`, `cart`, `users`, `factory`, `code`, `settings`, `logout`, `x`, `send`, `trash`, `copy`, `beaker`, `chevDown`, `chevUp`, `alert`, `check`, `terminal`, `refresh`, `wifi`, `wifiOff`, `panel`

**To add a new icon:**
```jsx
// Add to the Icons object in App.jsx
Icons.myIcon = () => <Svg><path d="..." /></Svg>
```

---

### `Svg`

Wrapper component for all SVG icons. Provides consistent viewBox and stroke settings.

```jsx
function Svg({ size = 16, children, className = '', style }) { ... }

// Props
// size     — number, px dimensions (default: 16)
// children — SVG path/shape elements
// className, style — pass-through
```

---

### `ModuleIcon`

Renders a colored SVG icon for a given SAP module.

```jsx
<ModuleIcon iconId="dollar" color="#16A34A" size={14} />

// Props
// iconId — key from the Icons object (e.g. 'grid', 'dollar', 'package')
// color  — CSS color string
// size   — icon size in px (default: 14)
```

---

### `CodeBlock`

Syntax-highlighted code block. Zero external dependencies — uses a custom tokenizer.

```jsx
<CodeBlock code="SELECT * FROM MARA WHERE MTART = 'FERT'." lang="abap" />

// Props
// code — the raw source code string
// lang — language hint: 'abap' | 'sql' | 'javascript' | 'python' | 'json' | 'text'
```

**Features:**
- Copy-to-clipboard button (shows "Copied!" feedback)
- Catppuccin Mocha dark theme
- Token classes: `tok-keyword`, `tok-string`, `tok-comment`, `tok-number`, `tok-op`, `tok-json-key`, `tok-boolean`, `tok-null`
- Language label in header

**Supported languages:**
| Lang | Highlights |
|---|---|
| `abap` | Keywords, strings, line/inline comments |
| `sql` | Keywords, strings, `--` comments |
| `javascript` | Keywords, strings, template literals, `//` and `/* */` comments |
| `python` | Keywords, strings, `#` comments |
| `json` | Keys (blue), strings (green), numbers (orange), booleans/null |

---

### `MarkdownRenderer`

Full GFM-compatible markdown parser as a React component. No external deps.

```jsx
<MarkdownRenderer content={markdownString} className="optional-extra-class" />

// Props
// content   — raw markdown string
// className — extra CSS class on the wrapper div
```

**Supported markdown elements:**

| Element | Syntax |
|---|---|
| Headings | `# H1`, `## H2`, `### H3` |
| Bold | `**text**` |
| Italic | `*text*` |
| Inline code | `` `code` `` |
| Code blocks | ` ```lang\ncode\n``` ` (uses `CodeBlock`) |
| Links | `[label](url)` |
| Unordered list | `- item` |
| Ordered list | `1. item` |
| Blockquote | `> text` |
| Horizontal rule | `---` |
| GFM table | `\| col \| col \|` with separator row |

**Status coloring in tables:** cells matching success/warning/error keywords are automatically highlighted (see `statusClass()`).

---

### `ToolResult`

Renders a SAP tool's raw result object. Auto-detects array-of-objects (table view) vs flat object (key-value grid).

```jsx
<ToolResult result={toolResultObject} />

// Props
// result — the JSON object returned from a SAP tool call
```

**Behavior:**
- Array of objects → renders a data table with formatted column headers
- Flat object → renders a key-value grid, with nested objects expanded
- Filters out `sap_source` and `status` metadata keys
- Status-aware cell coloring (success/warning/error)

---

### `SapSourceBadge`

Shows the SAP transaction code, BAPI, and table associated with a tool result.

```jsx
<SapSourceBadge source={{ tcode: 'ME23N', bapi: 'BAPI_PO_GETDETAIL', table: 'EKKO' }} />

// Props
// source.tcode  — SAP T-code (required)
// source.bapi   — BAPI name (optional, hidden if 'N/A')
// source.table  — SAP table (optional, hidden if 'N/A')
```

---

### `AnomalyPanel`

Displays anomaly/alert items from a research report.

```jsx
<AnomalyPanel anomalies={[{ severity: 'HIGH', message: 'Invoice overdue' }]} />

// Props
// anomalies — array of { severity: 'HIGH'|'MEDIUM'|'LOW', message: string }
```

---

### `ResearchReport`

Collapsible research report card. Renders anomalies, tool badges, markdown report, and SAP sources.

```jsx
<ResearchReport result={{
  formatted_report: '## Summary\n...',
  anomalies: [],
  tools_run: ['get_vendor_info', 'list_invoices'],
  sources_used: ['ME23N', 'FB03'],
  entity_id: 'V001',
}} />
```

---

### `MessageRow`

Renders a single chat message. Handles user bubbles, bot markdown responses, and research report messages.

```jsx
<MessageRow msg={{
  role: 'user' | 'bot',
  content: 'string',
  userInitial: 'A',          // single char for user avatar
  tool_called: 'fn_name',   // optional
  tool_result: {},           // optional
  sap_source: {},            // optional
  research_mode: false,      // optional
  research_result: {},       // optional
  request_id: 'uuid',        // optional
}} />
```

---

### `TypingIndicator`

Animated three-dot typing indicator shown while the AI is generating a response.

```jsx
<TypingIndicator />
// No props.
```

---

### `DevWarningBanner`

Dismissible warning banner shown when the JWT secret is insecure (dev mode).

```jsx
<DevWarningBanner />
// No props. Reads nothing from props — self-contained state.
```

---

### `Badge` (CSS class system)

```html
<!-- Tool name badge -->
<span class="badge badge-tool">get_vendor_info</span>

<!-- Research mode badge -->
<span class="badge badge-research">AUTO RESEARCH</span>

<!-- Request ID badge -->
<span class="badge badge-id">abc12345</span>

<!-- Role badge -->
<span class="badge-role" style="background:#0070D222;color:#0070D2">Administrator</span>
```

---

### `SettingsModal`

Full-featured configuration modal. Tabs: SAP Connection, MCP Servers, LLM/Ollama, Users & Roles (admin), Audit Logs (admin).

```jsx
<SettingsModal onClose={() => setShowSettings(false)} currentUser={currentUser} />

// Props
// onClose     — callback when modal is dismissed
// currentUser — { user_id, roles, full_name }
```

**Tab access:**
- All users: SAP Connection, MCP Servers, LLM / Ollama
- Admin only: Users & Roles, Audit Logs

---

### `Sidebar`

Dark navigation sidebar with SAP module buttons. Filtered by user's `allowedModules`.

```jsx
<Sidebar
  activeModule="FI/CO"
  onModuleClick={(id) => setActiveModule(id)}
  onReset={handleReset}
  sapMode="mock"
  allowedModules={['fi_co', 'mm']}  // null = all
/>
```

---

### `LoginScreen`

Full-page login form with demo account hints.

```jsx
<LoginScreen onLogin={(data) => handleLogin(data)} />

// Props
// onLogin — callback with { access_token, refresh_token, user_id, roles, full_name, warning? }
```

---

## Syntax Highlighter API

### `tokenizeCode(code, lang)`

Returns an array of React `<span>` nodes with syntax token classes.

```js
const tokens = tokenizeCode('SELECT * FROM MARA', 'sql')
// Returns: [<span className="tok-keyword">SELECT</span>, ...]
```

### `tokenizeJSON(code)`

Specialized tokenizer for JSON. Distinguishes object keys (`tok-json-key`) from string values (`tok-string`).

```js
const tokens = tokenizeJSON('{"key": "value", "count": 42}')
```

---

## Markdown Parser API

### `parseInline(text, baseKey?)`

Parses inline markdown (bold, italic, code, links) from a string. Returns an array of React nodes/strings.

```js
const nodes = parseInline('**Hello** `world`')
// Returns: [<strong>Hello</strong>, ' ', <code>world</code>]
```

### `MarkdownRenderer` component

Parses full block-level + inline markdown. Use this everywhere markdown content needs to be rendered.

---

## Status Colors

`statusClass(value)` returns a CSS class based on the cell value:

| Return | Class | Style |
|---|---|---|
| `'ok'`, `'open'`, `'active'`, `'paid'`, `'delivered'`, `'success'`, `'released'` | `st-success` | Green, bold |
| `'blocked'`, `'error'`, `'cancelled'`, `'failed'`, `'poor'` | `st-error` | Red, bold |
| `'pending'`, `'partial'`, `'in_progress'`, `'in_transit'`, `'modifiable'`, `'needs_review'` | `st-warning` | Amber, bold |

---

## Adding a New Component

1. Write the component in `App.jsx` (or a new file if large)
2. Add CSS to `App.css` following the naming convention
3. Document it in this file under the Components section
4. Use CSS custom properties from the design system — never hardcode colors or spacing
5. No external libraries — build from scratch

---

## File Structure

```
frontend/
├── src/
│   ├── index.css     # Design tokens, reset, animations
│   ├── App.css       # All component styles
│   └── App.jsx       # All components + icons + parsers
├── COMPONENTS.md     # This file — component documentation
└── package.json      # react + react-dom only
```
