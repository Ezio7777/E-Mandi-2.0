"use client";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
  title: string;
  data: { label: string; value: number }[];
  kind?: "line" | "bar";
  unit?: string;
}

/** Fixed-height container inside a Card keeps charts legible from 320px up. */
export function ChartCard({ title, data, kind = "line", unit }: Props) {
  const axis = { stroke: "hsl(var(--muted-foreground))", fontSize: 12, tickLine: false, axisLine: false } as const;
  const tooltip = {
    contentStyle: {
      background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12, color: "hsl(var(--popover-foreground))",
    },
    formatter: (v: number) => [`${v}${unit ?? ""}`, title] as [string, string],
  };
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-base">{title}</CardTitle></CardHeader>
      <CardContent>
        <div className="h-56 w-full sm:h-64" role="img" aria-label={`${title} chart`}>
          <ResponsiveContainer width="100%" height="100%" debounce={120}>
            {kind === "line" ? (
              <LineChart data={data} margin={{ left: -16, right: 8, top: 8 }}>
                <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
                <XAxis dataKey="label" {...axis} interval="preserveStartEnd" />
                <YAxis {...axis} width={48} />
                <Tooltip {...tooltip} />
                <Line dataKey="value" stroke="hsl(var(--primary))" strokeWidth={2.5} dot={false} />
              </LineChart>
            ) : (
              <BarChart data={data} margin={{ left: -16, right: 8, top: 8 }}>
                <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
                <XAxis dataKey="label" {...axis} interval="preserveStartEnd" />
                <YAxis {...axis} width={48} />
                <Tooltip {...tooltip} cursor={{ fill: "hsl(var(--accent))" }} />
                <Bar dataKey="value" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
