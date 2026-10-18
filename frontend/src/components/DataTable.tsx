import type { ReactNode } from "react";
import { t } from "../i18n";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  numeric?: boolean;
}

export function DataTable<T>({ columns, rows, caption, empty }: { columns: Column<T>[]; rows: T[]; caption?: string; empty?: string }) {
  if (!rows.length) return <p className="muted small">{empty ?? t("No rows.")}</p>;
  return (
    <div className="table-wrap">
      <table className="data">
        {caption && <caption>{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={c.numeric ? "num" : undefined}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} className={c.numeric ? "num" : undefined} translate={c.numeric ? "no" : undefined}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A collapsible table view that accompanies every chart. */
export function TableToggle({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <details className="table-toggle">
      <summary>{label ?? t("Show data table")}</summary>
      <div style={{ marginTop: 8 }}>{children}</div>
    </details>
  );
}
