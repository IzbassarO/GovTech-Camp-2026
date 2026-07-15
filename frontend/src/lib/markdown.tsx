import type { ReactNode } from "react";

// Minimal renderer for the constrained markdown our report service emits
// (headings, blockquotes, bullet lists, bold/italic inline). Not a general
// markdown parser — inputs are server-generated and predictable.

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const regex = /\*\*(.+?)\*\*|_(.+?)_/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    if (match[1] !== undefined) {
      nodes.push(
        <strong key={`${keyPrefix}-b-${i}`} className="font-semibold text-slate-900">
          {match[1]}
        </strong>,
      );
    } else if (match[2] !== undefined) {
      nodes.push(
        <em key={`${keyPrefix}-i-${i}`} className="text-slate-500">
          {match[2]}
        </em>,
      );
    }
    last = regex.lastIndex;
    i += 1;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function Markdown({ content }: { content: string }) {
  const lines = content.split("\n");
  const blocks: ReactNode[] = [];
  let list: string[] = [];

  const flushList = (key: string) => {
    if (list.length === 0) return;
    const items = list;
    list = [];
    blocks.push(
      <ul key={key} className="ml-1 list-inside list-disc space-y-1 text-sm text-slate-700">
        {items.map((item, i) => (
          <li key={i}>{renderInline(item, `${key}-${i}`)}</li>
        ))}
      </ul>,
    );
  };

  lines.forEach((raw, index) => {
    const line = raw.trimEnd();
    const key = `line-${index}`;
    if (line.startsWith("- ")) {
      list.push(line.slice(2));
      return;
    }
    flushList(`${key}-list`);
    if (line.startsWith("# ")) {
      blocks.push(
        <h2 key={key} className="text-lg font-semibold text-slate-900">
          {renderInline(line.slice(2), key)}
        </h2>,
      );
    } else if (line.startsWith("## ")) {
      blocks.push(
        <h3 key={key} className="mt-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
          {renderInline(line.slice(3), key)}
        </h3>,
      );
    } else if (line.startsWith("> ")) {
      blocks.push(
        <blockquote
          key={key}
          className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800"
        >
          {renderInline(line.slice(2), key)}
        </blockquote>,
      );
    } else if (line.trim() === "") {
      // skip blank lines (spacing handled by container)
    } else {
      blocks.push(
        <p key={key} className="text-sm leading-relaxed text-slate-700">
          {renderInline(line, key)}
        </p>,
      );
    }
  });
  flushList("final-list");

  return <div className="space-y-2">{blocks}</div>;
}
