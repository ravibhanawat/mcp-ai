import { useState } from 'react'

// ─── Syntax Highlighter ───────────────────────────────────────────────────────

const KW = {
  abap: new Set('DATA,TYPES,CLASS,METHOD,ENDMETHOD,IF,ELSE,ELSEIF,ENDIF,LOOP,AT,ENDAT,ENDLOOP,SELECT,FROM,INTO,WHERE,AND,OR,NOT,IS,MOVE,CLEAR,APPEND,READ,WRITE,FORM,ENDFORM,PERFORM,CALL,FUNCTION,TABLE,OF,TYPE,LIKE,IMPORTING,EXPORTING,CHANGING,EXCEPTIONS,BEGIN,END,REPORT,TABLES,PARAMETERS,CHECK,RETURN,RAISE,EXIT,CONTINUE,SORT,MODIFY,DELETE,INSERT,UPDATE,COMMIT,WHEN,CASE,ENDCASE,CREATE,OBJECT,FINAL,REFERENCE,USING,RESULT,LET,WHILE,ENDWHILE,DO,ENDDO,TRY,CATCH,ENDTRY,CONCATENATE,SPLIT,CONDENSE,FIND,REPLACE,TRANSLATE,GET,SET,COLLECT,NEW,FIELD-SYMBOLS,ASSIGN,COMPONENT,STRUCTURE,IMPLEMENTATION,DEFINITION,SECTION,PUBLIC,PRIVATE,PROTECTED,METHODS,ATTRIBUTES,CONSTANTS,VALUE,INITIAL'.split(',')),
  sql: new Set('SELECT,FROM,WHERE,AND,OR,NOT,IN,LIKE,BETWEEN,IS,NULL,INSERT,INTO,VALUES,UPDATE,SET,DELETE,CREATE,TABLE,ALTER,DROP,INDEX,JOIN,INNER,LEFT,RIGHT,OUTER,FULL,ON,GROUP,BY,HAVING,ORDER,ASC,DESC,LIMIT,OFFSET,DISTINCT,AS,UNION,ALL,EXISTS,COUNT,SUM,AVG,MIN,MAX,CASE,WHEN,THEN,ELSE,END,WITH,TOP,PRIMARY,KEY,FOREIGN,REFERENCES,CONSTRAINT,DEFAULT,UNIQUE'.split(',')),
  javascript: new Set('const,let,var,function,return,if,else,for,while,do,switch,case,break,continue,class,extends,import,export,default,from,async,await,new,this,super,try,catch,finally,throw,typeof,instanceof,null,undefined,true,false,of,in,delete,void,yield,static,get,set,constructor,NaN,Infinity'.split(',')),
  python: new Set('def,class,return,if,elif,else,for,while,import,from,as,in,not,and,or,is,None,True,False,try,except,finally,raise,with,pass,break,continue,lambda,yield,global,nonlocal,del,assert,self,super,print,len,range,type'.split(',')),
}

function tokenizeJSON(code) {
  const out = []; let i = 0; let k = 0
  const s = (cls, text) => <span key={k++} className={`tok-${cls}`}>{text}</span>
  while (i < code.length) {
    const ch = code[i]
    if (ch === '"') {
      let j = i + 1
      while (j < code.length && code[j] !== '"') { if (code[j] === '\\') j++; j++ }
      j++
      const str = code.slice(i, j)
      let nk = j; while (nk < code.length && /\s/.test(code[nk])) nk++
      out.push(code[nk] === ':' ? s('json-key', str) : s('string', str))
      i = j; continue
    }
    if (/[-0-9]/.test(ch) && (ch !== '-' || /[0-9]/.test(code[i + 1]))) {
      let j = i + 1; while (j < code.length && /[0-9.eE+\-]/.test(code[j])) j++
      out.push(s('number', code.slice(i, j))); i = j; continue
    }
    if (code.startsWith('true', i)) { out.push(s('boolean', 'true')); i += 4; continue }
    if (code.startsWith('false', i)) { out.push(s('boolean', 'false')); i += 5; continue }
    if (code.startsWith('null', i)) { out.push(s('null', 'null')); i += 4; continue }
    if (/[{}\[\]:,]/.test(ch)) { out.push(s('op', ch)); i++; continue }
    out.push(<span key={k++}>{ch}</span>); i++
  }
  return out
}

function tokenizeCode(code, lang) {
  const l = (lang || '').toLowerCase()
  if (l === 'json') return tokenizeJSON(code)
  const kw = KW[l] || KW.javascript
  const out = []; let i = 0; let k = 0
  const s = (cls, text) => <span key={k++} className={`tok-${cls}`}>{text}</span>

  while (i < code.length) {
    const ch = code[i]
    // Line comments
    if ((l === 'abap' && ch === '*' && (i === 0 || code[i - 1] === '\n')) ||
      (l === 'python' && ch === '#') ||
      (l === 'sql' && ch === '-' && code[i + 1] === '-') ||
      (l === 'javascript' && ch === '/' && code[i + 1] === '/')) {
      let j = code.indexOf('\n', i); if (j === -1) j = code.length
      out.push(s('comment', code.slice(i, j))); i = j; continue
    }
    // ABAP inline comment
    if (l === 'abap' && ch === '"') {
      let j = code.indexOf('\n', i); if (j === -1) j = code.length
      out.push(s('comment', code.slice(i, j))); i = j; continue
    }
    // Block comment /* */
    if (l === 'javascript' && ch === '/' && code[i + 1] === '*') {
      let j = code.indexOf('*/', i + 2); if (j === -1) j = code.length - 2
      out.push(s('comment', code.slice(i, j + 2))); i = j + 2; continue
    }
    // Strings
    if (ch === '"' || ch === "'") {
      const q = ch; let j = i + 1
      while (j < code.length && code[j] !== q) { if (code[j] === '\\') j++; j++ }
      out.push(s('string', code.slice(i, j + 1))); i = j + 1; continue
    }
    // Template literals
    if (l === 'javascript' && ch === '`') {
      let j = i + 1
      while (j < code.length && code[j] !== '`') { if (code[j] === '\\') j++; j++ }
      out.push(s('string', code.slice(i, j + 1))); i = j + 1; continue
    }
    // Numbers
    if (/[0-9]/.test(ch)) {
      let j = i + 1; while (j < code.length && /[0-9.eE_]/.test(code[j])) j++
      out.push(s('number', code.slice(i, j))); i = j; continue
    }
    // Identifiers / keywords
    if (/[a-zA-Z_$]/.test(ch)) {
      let j = i + 1; while (j < code.length && /[a-zA-Z0-9_$\-]/.test(code[j])) j++
      const word = code.slice(i, j)
      const isKw = kw.has(word) || kw.has(word.toUpperCase())
      out.push(isKw ? s('keyword', word) : <span key={k++}>{word}</span>)
      i = j; continue
    }
    // Operators
    if (/[{}[\]().,;:=<>!&|^~%@+\-*/]/.test(ch)) { out.push(s('op', ch)); i++; continue }
    out.push(<span key={k++}>{ch}</span>); i++
  }
  return out
}

// ─── Code Block ───────────────────────────────────────────────────────────────

function CodeBlock({ code, lang }) {
  const [copied, setCopied] = useState(false)
  const doCopy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true); setTimeout(() => setCopied(false), 1800)
  }
  const tokens = tokenizeCode(code, lang)
  return (
    <div className="code-block">
      <div className="code-head">
        <span className="code-lang">{lang || 'text'}</span>
        <button className={`code-copy-btn ${copied ? 'copied' : ''}`} onClick={doCopy}>
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre className="code-content">{tokens}</pre>
    </div>
  )
}

// ─── Markdown Renderer ────────────────────────────────────────────────────────

function parseInline(text, baseKey = 0) {
  const out = []; let i = 0; let k = baseKey
  while (i < text.length) {
    // Bold **
    if (text[i] === '*' && text[i + 1] === '*') {
      const end = text.indexOf('**', i + 2)
      if (end !== -1) { out.push(<strong key={k++}>{text.slice(i + 2, end)}</strong>); i = end + 2; continue }
    }
    // Italic *
    if (text[i] === '*') {
      const end = text.indexOf('*', i + 1)
      if (end !== -1) { out.push(<em key={k++}>{text.slice(i + 1, end)}</em>); i = end + 1; continue }
    }
    // Inline code `
    if (text[i] === '`') {
      const end = text.indexOf('`', i + 1)
      if (end !== -1) { out.push(<code key={k++} className="inline-code">{text.slice(i + 1, end)}</code>); i = end + 1; continue }
    }
    // Link [label](url)
    if (text[i] === '[') {
      const te = text.indexOf(']', i + 1)
      if (te !== -1 && text[te + 1] === '(') {
        const ue = text.indexOf(')', te + 2)
        if (ue !== -1) {
          out.push(<a key={k++} href={text.slice(te + 2, ue)} target="_blank" rel="noreferrer" className="md-link">{text.slice(i + 1, te)}</a>)
          i = ue + 1; continue
        }
      }
    }
    // Plain chars
    let next = text.slice(i).search(/[*`\[]/)
    if (next <= 0) { out.push(text[i]); i++ }
    else { out.push(text.slice(i, i + next)); i += next }
  }
  return out
}

function statusClass(val) {
  const s = String(val).toLowerCase()
  if (['ok', 'open', 'active', 'paid', 'delivered', 'success', 'released'].includes(s)) return 'st-success'
  if (['blocked', 'error', 'cancelled', 'failed', 'poor'].includes(s)) return 'st-error'
  if (['pending', 'partial', 'in_progress', 'in_transit', 'modifiable', 'needs_review'].includes(s)) return 'st-warning'
  return ''
}

export default function MarkdownRenderer({ content, className = '' }) {
  const blocks = []; const lines = content.split('\n'); let i = 0; let bk = 0
  while (i < lines.length) {
    const line = lines[i]
    // Fenced code block
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim() || 'text'; const codeLines = []; i++
      while (i < lines.length && !lines[i].startsWith('```')) { codeLines.push(lines[i]); i++ }
      i++; blocks.push(<CodeBlock key={bk++} code={codeLines.join('\n')} lang={lang} />); continue
    }
    // Headings
    if (line.startsWith('### ')) { blocks.push(<h3 key={bk++} className="md-h3">{parseInline(line.slice(4))}</h3>); i++; continue }
    if (line.startsWith('## ')) { blocks.push(<h2 key={bk++} className="md-h2">{parseInline(line.slice(3))}</h2>); i++; continue }
    if (line.startsWith('# ')) { blocks.push(<h1 key={bk++} className="md-h1">{parseInline(line.slice(2))}</h1>); i++; continue }
    // HR
    if (/^[-*_]{3,}$/.test(line.trim())) { blocks.push(<hr key={bk++} className="md-hr" />); i++; continue }
    // Blockquote
    if (line.startsWith('> ')) {
      const ql = []; while (i < lines.length && lines[i].startsWith('> ')) { ql.push(lines[i].slice(2)); i++ }
      blocks.push(<blockquote key={bk++} className="md-blockquote">{parseInline(ql.join(' '))}</blockquote>); continue
    }
    // GFM Table
    if (line.includes('|') && i + 1 < lines.length && /^[\s|:-]+$/.test(lines[i + 1])) {
      const parseCells = (r) => r.split('|').filter((_, idx, a) => idx > 0 && idx < a.length - 1).map(c => c.trim())
      const headers = parseCells(line); i += 2; const rows = []
      while (i < lines.length && lines[i].includes('|')) { rows.push(parseCells(lines[i])); i++ }
      blocks.push(
        <div key={bk++} className="md-table-wrap">
          <table className="md-table">
            <thead><tr>{headers.map((h, ci) => <th key={ci} className="md-th">{parseInline(h)}</th>)}</tr></thead>
            <tbody>{rows.map((row, ri) => <tr key={ri}>{row.map((c, ci) => <td key={ci} className={`md-td ${statusClass(c)}`}>{parseInline(c)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      ); continue
    }
    // Unordered list
    if (/^[-*+]\s/.test(line)) {
      const items = []; while (i < lines.length && /^[-*+]\s/.test(lines[i])) { items.push(lines[i].replace(/^[-*+]\s/, '')); i++ }
      blocks.push(<ul key={bk++} className="md-ul">{items.map((it, idx) => <li key={idx} className="md-li">{parseInline(it)}</li>)}</ul>); continue
    }
    // Ordered list
    if (/^\d+\.\s/.test(line)) {
      const items = []; while (i < lines.length && /^\d+\.\s/.test(lines[i])) { items.push(lines[i].replace(/^\d+\.\s/, '')); i++ }
      blocks.push(<ol key={bk++} className="md-ol">{items.map((it, idx) => <li key={idx} className="md-li">{parseInline(it)}</li>)}</ol>); continue
    }
    // Empty line
    if (line.trim() === '') { i++; continue }
    // Paragraph (greedy)
    const pl = []
    while (i < lines.length && lines[i].trim() !== '' && !lines[i].startsWith('```') && !lines[i].startsWith('#') && !lines[i].startsWith('> ') && !/^[-*+]\s/.test(lines[i]) && !/^\d+\.\s/.test(lines[i]) && !/^[-*_]{3,}$/.test(lines[i].trim()) && !lines[i].includes('|')) {
      pl.push(lines[i]); i++
    }
    if (pl.length) blocks.push(<p key={bk++} className="md-p">{pl.map((l2, pi) => <span key={pi}>{parseInline(l2)}{pi < pl.length - 1 && <br />}</span>)}</p>)
  }
  return <div className={`md-body ${className}`}>{blocks}</div>
}
