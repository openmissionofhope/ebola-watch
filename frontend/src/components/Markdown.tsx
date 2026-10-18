// A deliberately tiny Markdown renderer for situation reports. It builds React
// elements (no innerHTML), supporting headings, lists, block quotes, bold and
// paragraphs. Everything else is rendered as plain text.
//
// Reports are generated in English by the backend. Each line is translated
// segment by segment around **bold** markers (the same split that
// scripts/i18n-check.ts uses for coverage); segments without a catalog entry
// stay in English.
import type { ReactNode } from "react";
import { fmtDateTime, tx } from "../i18n";

const STAMPED = /^(\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?): (.+)$/s; // "<timestamp>: <message>" (alert lines)

/** Translate a segment, keeping its surrounding whitespace. */
function translateSegment(segment: string): string {
  const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(segment);
  if (!m || !m[2]) return segment;
  const stamped = STAMPED.exec(m[2]);
  const text = stamped ? `${fmtDateTime(stamped[1])}: ${tx(stamped[2])}` : tx(m[2]);
  return m[1] + text + m[3];
}

function inline(text: string): ReactNode[] {
  // odd indices of the split are the contents of **bold** markers
  return text
    .split(/\*\*(.+?)\*\*/)
    .map((part, i) => (i % 2 ? <strong key={i}>{translateSegment(part)}</strong> : translateSegment(part)))
    .filter((part) => part !== "");
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
