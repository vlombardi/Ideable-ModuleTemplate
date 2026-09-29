import { useMemo } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  AreaChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'
import { useTranslation } from '../hooks/useTranslation'

/**
 * TimeSeriesChart — @ideable/ui framework chart widget.
 *
 * Data-driven and page-agnostic: it never fetches. All series/axis labels are
 * passed in already translated by the page; the only string it resolves itself
 * is the empty-state fallback (`chart.noData`).
 *
 * Colors, gridlines and axis text derive from framework design tokens
 * (`hsl(var(--ideable-*))`) so light/dark parity is automatic — no `dark:` variants.
 * Render inside an `.ideable-scope` subtree so the tokens resolve.
 *
 * Bundle rule: import this widget (and therefore Recharts) only through code paths
 * a module actually uses. When unused (e.g. only the dev-only Widget Examples page
 * references it, excluded from published builds via `WIDGET_EXAMPLES=false`),
 * Recharts is tree-shaken out of the published image. See shared-ui-widgets-specs.md.
 */

export interface TimeSeriesPoint {
  x: string | number
  [seriesKey: string]: string | number
}

export interface TimeSeriesSeries {
  key: string
  label: string
  color?: string
}

export interface TimeSeriesChartProps {
  data: TimeSeriesPoint[]
  series: TimeSeriesSeries[]
  xKey?: string
  variant?: 'line' | 'area'
  height?: number
  xTickFormatter?: (value: string | number) => string
  yTickFormatter?: (value: number) => string
  emptyLabel?: string
}

// Accessible categorical palette for multi-series charts. Single-series charts
// use the theme-aware primary token instead so they follow light/dark mode.
const CATEGORICAL_PALETTE = [
  'hsl(217 91% 60%)', // blue
  'hsl(142 71% 45%)', // green
  'hsl(38 92% 50%)', // amber
  'hsl(0 84% 60%)', // red
  'hsl(280 65% 60%)', // purple
  'hsl(174 62% 47%)', // teal
  'hsl(330 81% 60%)', // pink
]

const TOKEN = {
  grid: 'hsl(var(--ideable-border))',
  axis: 'hsl(var(--ideable-muted-foreground))',
  primary: 'hsl(var(--ideable-primary))',
  popover: 'hsl(var(--ideable-popover))',
  popoverForeground: 'hsl(var(--ideable-popover-foreground))',
  border: 'hsl(var(--ideable-border))',
}

function resolveSeriesColor(series: TimeSeriesSeries, index: number, total: number): string {
  if (series.color) return series.color
  if (total === 1) return TOKEN.primary
  return CATEGORICAL_PALETTE[index % CATEGORICAL_PALETTE.length]
}

export function TimeSeriesChart({
  data,
  series,
  xKey = 'x',
  variant = 'line',
  height = 288,
  xTickFormatter,
  yTickFormatter,
  emptyLabel,
}: TimeSeriesChartProps) {
  const { t } = useTranslation()

  const colors = useMemo(
    () => series.map((s, i) => resolveSeriesColor(s, i, series.length)),
    [series],
  )

  if (!data || data.length === 0) {
    return (
      <div
        className="ideable:flex ideable:items-center ideable:justify-center ideable:rounded-md ideable:border ideable:text-sm ideable:text-muted-foreground"
        style={{ height }}
      >
        {emptyLabel ?? t('chart.noData')}
      </div>
    )
  }

  const axisTick = { fill: TOKEN.axis, fontSize: 12 }
  const tooltipContentStyle = {
    backgroundColor: TOKEN.popover,
    border: `1px solid ${TOKEN.border}`,
    borderRadius: 'var(--ideable-radius, 0.5rem)',
    color: TOKEN.popoverForeground,
    fontSize: 12,
  }

  const ChartRoot = variant === 'area' ? AreaChart : LineChart

  return (
    <div className="ideable:w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ChartRoot data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid stroke={TOKEN.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey={xKey}
            tick={axisTick}
            tickFormatter={xTickFormatter}
            stroke={TOKEN.grid}
            tickLine={false}
          />
          <YAxis
            tick={axisTick}
            tickFormatter={yTickFormatter}
            stroke={TOKEN.grid}
            tickLine={false}
            width={40}
          />
          <Tooltip contentStyle={tooltipContentStyle} cursor={{ stroke: TOKEN.grid }} />
          <Legend wrapperStyle={{ fontSize: 12, color: TOKEN.axis }} />
          {series.map((s, i) =>
            variant === 'area' ? (
              <Area
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={colors[i]}
                fill={colors[i]}
                fillOpacity={0.15}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            ) : (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={colors[i]}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            ),
          )}
        </ChartRoot>
      </ResponsiveContainer>
    </div>
  )
}

export default TimeSeriesChart
