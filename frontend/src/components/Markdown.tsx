// A deliberately tiny Markdown renderer for situation reports. It builds React
// elements (no innerHTML), supporting headings, lists, block quotes, bold and
// paragraphs. Everything else is rendered as plain text.
import type { ReactNode } from "react";

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*(.+?)\*\*/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(<strong key={i++}>{m[1]}</strong>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let para: string[] = [];
  let quote: string[] = [];
  let k = 0;
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={k++}>
          {list.map((li, j) => (
            <li key={j}>{inline(li)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
    if (para.length) {
      const ps = para;
      blocks.push(
        <p key={k++}>
          {ps.map((l, j) => (
            <span key={j}>
              {inline(l)}
              {j < ps.length - 1 && <br />}
            </span>
          ))}
        </p>,
      );
      para = [];
    }
    if (quote.length) {
      blocks.push(<blockquote key={k++}>{inline(quote.join(" "))}</blockquote>);
      quote = [];
    }
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      flush();
      const level = Math.min(h[1].length + 1, 4);
      const content = inline(h[2]);
      blocks.push(level === 2 ? <h2 key={k++}>{content}</h2> : level === 3 ? <h3 key={k++}>{content}</h3> : <h4 key={k++}>{content}</h4>);
    } else if (/^\s*[-*]\s+/.test(line)) {
      if (para.length || quote.length) {
        const keep = list;
        list = [];
        flush();
        list = keep;
      }
      list.push(line.replace(/^\s*[-*]\s+/, ""));
    } else if (/^>\s?/.test(line)) {
      if (list.length || para.length) flush();
      quote.push(line.replace(/^>\s?/, ""));
    } else if (!line.trim()) {
      flush();
    } else {
      if (list.length || quote.length) flush();
      para.push(line);
    }
  }
  flush();
  return <div className="markdown">{blocks}</div>;
}
