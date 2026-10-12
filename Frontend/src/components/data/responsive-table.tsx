import { cn } from "@/utils/cn";

export interface Column<T> {
  key: string;
  header: string;
  cell: (row: T) => React.ReactNode;
  /** Shown as the card title on mobile */
  primary?: boolean;
  className?: string;
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  caption: string;
}

/** Real table from md up; stacked label/value cards below md. No horizontal scroll on phones. */
export function ResponsiveTable<T>({ columns, rows, rowKey, caption }: Props<T>) {
  const primary = columns.find((c) => c.primary) ?? columns[0]!;
  return (
    <>
      <div className="hidden overflow-x-auto rounded-lg border md:block">
        <table className="w-full text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="bg-muted/60 text-left text-muted-foreground">
            <tr>{columns.map((c) => <th key={c.key} scope="col" className="px-4 py-3 font-medium">{c.header}</th>)}</tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((r) => (
              <tr key={rowKey(r)} className="hover:bg-muted/30">
                {columns.map((c) => <td key={c.key} className={cn("px-4 py-3 align-middle", c.className)}>{c.cell(r)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="space-y-3 md:hidden">
        {rows.map((r) => (
          <li key={rowKey(r)} className="rounded-lg border bg-card p-4">
            <div className="font-medium">{primary.cell(r)}</div>
            <dl className="mt-2 space-y-1.5 text-sm">
              {columns.filter((c) => c !== primary).map((c) => (
                <div key={c.key} className="flex items-start justify-between gap-4">
                  <dt className="text-muted-foreground">{c.header}</dt>
                  <dd className="min-w-0 text-right">{c.cell(r)}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}
