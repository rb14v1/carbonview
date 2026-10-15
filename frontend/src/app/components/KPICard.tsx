import { LucideIcon, TrendingUp, TrendingDown, Cloud, Flame, Zap, Truck, Activity } from 'lucide-react';

interface KPICardProps {
  title: string;
  value: number | string;
  unit: string;
  trend: number;
  trendDirection?: 'increase' | 'decrease' | 'neutral';
  trendDisplayValue?: string;
  trendLabel?: string;
  status: 'success' | 'warning' | 'error';
  icon?: LucideIcon;
  details?: Array<{
    label: string;
    subtitle?: string;
    value: string;
  }>;
  detailTitle?: string;
  detailSummary?: string;
  hoverHint?: string;
  showDetailTotal?: boolean;
}

export function KPICard({
  title,
  value,
  unit,
  trend,
  trendDirection,
  trendDisplayValue,
  trendLabel = 'vs last month',
  status,
  icon,
  details = [],
  detailTitle = 'Breakdown',
  detailSummary,
  hoverHint = 'Hover to inspect scope breakdown',
  showDetailTotal = true,
}: KPICardProps) {
  let DisplayIcon = icon || Activity;
  const lowerTitle = title.toLowerCase();
  
  if (lowerTitle.includes('total')) DisplayIcon = Cloud;
  else if (lowerTitle.includes('scope 1')) DisplayIcon = Flame;
  else if (lowerTitle.includes('scope 2')) DisplayIcon = Zap;
  else if (lowerTitle.includes('scope 3')) DisplayIcon = Truck;

  const formatValue = (val: number | string) => {
    if (typeof val === 'number') {
      if (val >= 1000) return (val / 1000).toFixed(1) + 'K';
      return val.toString();
    }
    return val;
  };

  const statusThemes = {
    success: { iconBg: 'bg-emerald-50', iconText: 'text-emerald-700', cardAccent: 'from-emerald-50/70 via-white to-white', border: 'border-emerald-100' },
    warning: { iconBg: 'bg-amber-50', iconText: 'text-amber-700', cardAccent: 'from-amber-50/70 via-white to-white', border: 'border-amber-100' },
    error: { iconBg: 'bg-rose-50', iconText: 'text-rose-700', cardAccent: 'from-rose-50/70 via-white to-white', border: 'border-rose-100' },
  };

  const theme = statusThemes[status];
  const hasDetails = details.length > 0;
  const resolvedTrendDirection = trendDirection || (trend > 0 ? 'increase' : trend < 0 ? 'decrease' : 'neutral');
  const trendPillClassName =
    resolvedTrendDirection === 'increase'
      ? 'bg-rose-50/80 text-rose-600'
      : resolvedTrendDirection === 'decrease'
        ? 'bg-emerald-50/80 text-emerald-600'
        : 'bg-slate-100/80 text-slate-600';
  const trendText = trendDisplayValue || `${Math.abs(trend)}%`;

  return (
    <div className={`group relative flex h-full flex-col overflow-visible rounded-[24px] border bg-gradient-to-br p-6 shadow-[0_12px_30px_rgba(15,23,42,0.06)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_20px_40px_rgba(15,23,42,0.1)] ${theme.cardAccent} ${theme.border}`}>
      
      <div className="mb-5 flex items-start justify-between">
        <div className={`rounded-2xl p-3 ${theme.iconBg}`}>
          <DisplayIcon className={`h-5 w-5 ${theme.iconText}`} />
        </div>
      </div>

      <h3 className="mb-1 text-sm font-medium text-slate-500">{title}</h3>

      <div className="mb-4 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-3xl font-semibold tracking-tight text-slate-950 xl:text-4xl">
          {formatValue(value)}
        </span>
        <span className="text-xs font-medium text-slate-400 sm:text-sm">{unit}</span>
      </div>

      <div className="mt-auto flex flex-wrap items-center gap-2">
        <div className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${trendPillClassName}`}>
          {resolvedTrendDirection === 'increase' ? (
            <TrendingUp className="h-3.5 w-3.5" />
          ) : resolvedTrendDirection === 'decrease' ? (
            <TrendingDown className="h-3.5 w-3.5" />
          ) : (
            <Activity className="h-3.5 w-3.5" />
          )}
          <span>{trendText}</span>
        </div>
        <span className="text-xs font-medium text-slate-400">{trendLabel}</span>
      </div>

      {hasDetails && (
        <>
          <div className="pointer-events-none absolute left-4 right-4 top-4 z-20 translate-y-2 rounded-2xl border border-white/60 bg-white/55 p-4 opacity-0 shadow-2xl backdrop-blur-md transition-all duration-200 group-hover:translate-y-0 group-hover:opacity-100">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{detailTitle}</p>
                <p className="text-sm font-semibold text-slate-900">{title}</p>
                {detailSummary ? <p className="mt-1 text-xs text-slate-500">{detailSummary}</p> : null}
              </div>
              {showDetailTotal ? (
                <div className="text-right">
                  <p className="text-xs text-slate-400">Total</p>
                  <p className="text-sm font-semibold text-slate-900">{value} {unit}</p>
                </div>
              ) : null}
            </div>
            <div className="space-y-2">
              {details.map((detail) => (
                <div key={`${detail.label}-${detail.value}`} className="flex items-center justify-between rounded-xl bg-slate-50/90 px-3 py-2">
                  <div>
                    <p className="text-xs font-medium text-slate-800">{detail.label}</p>
                    {detail.subtitle ? <p className="text-[11px] text-slate-500">{detail.subtitle}</p> : null}
                  </div>
                  <span className="text-sm font-semibold text-slate-900">{detail.value}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
