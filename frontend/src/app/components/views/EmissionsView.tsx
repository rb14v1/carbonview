import { useEffect, useMemo, useState } from 'react';
import { Filter, Flame, Zap, Building2, Activity } from 'lucide-react';
import { EmissionsLineChart } from '../EmissionsLineChart';
import { DashboardSummaryResponse, ScopeBreakdown, fetchDashboardSummary } from '../../api';

function formatNumber(value: number) {
  return Number(value.toFixed(1)).toLocaleString();
}

function toTrend(summary: DashboardSummaryResponse, key: 'scope_1' | 'scope_2' | 'scope_3' | 'total_co2e') {
  const points = summary.yearly_emissions;
  const latest = points[points.length - 1];
  const previous = points[points.length - 2];

  if (!latest || !previous || !previous[key]) {
    return 0;
  }

  return Number((((latest[key] - previous[key]) / previous[key]) * 100).toFixed(1));
}

function scopeCardStyles(code: ScopeBreakdown['code']) {
  if (code === 'S1') return 'from-teal-50 to-white border-teal-200';
  if (code === 'S2') return 'from-amber-50 to-white border-amber-200';
  return 'from-rose-50 to-white border-rose-200';
}

function scopeIcon(code: ScopeBreakdown['code']) {
  if (code === 'S1') return Flame;
  if (code === 'S2') return Zap;
  return Building2;
}

export function EmissionsView() {
  const [selectedYear, setSelectedYear] = useState<number | 'all'>('all');
  const [availableYears, setAvailableYears] = useState<number[]>([]);
  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchDashboardSummary()
      .then((response) => {
        setAvailableYears(response.yearly_emissions.map((item) => item.year));
        const latestYear = response.highlights.latest_year?.year;
        setSelectedYear(latestYear ?? 'all');
      })
      .catch((err) => {
        console.error('EMISSIONS YEAR API ERROR:', err);
        setError('Unable to load available reporting years.');
        setIsLoading(false);
      });
  }, []);

  useEffect(() => {
    const filters = selectedYear === 'all' ? {} : { year: selectedYear };

    fetchDashboardSummary(filters)
      .then((response) => {
        setSummary(response);
        setError('');
      })
      .catch((err) => {
        console.error('EMISSIONS API ERROR:', err);
        setError('Unable to load emissions analytics right now.');
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [selectedYear]);

  const sortedMonthlyEmissions = useMemo(() => {
    return [...(summary?.monthly_emissions || [])].sort((a, b) => {
      if (a.year !== b.year) {
        return a.year - b.year;
      }
      return a.month - b.month;
    });
  }, [summary]);

  const activeYearTotals = useMemo(() => {
    if (!summary) {
      return {
        total: 0,
        scope1: 0,
        scope2: 0,
        scope3: 0,
      };
    }

    if (sortedMonthlyEmissions.length > 0) {
      return sortedMonthlyEmissions.reduce(
        (totals, item) => ({
          total: totals.total + item.total_co2e,
          scope1: totals.scope1 + item.scope_1,
          scope2: totals.scope2 + item.scope_2,
          scope3: totals.scope3 + item.scope_3,
        }),
        { total: 0, scope1: 0, scope2: 0, scope3: 0 },
      );
    }

    const latestYear = summary.yearly_emissions[summary.yearly_emissions.length - 1];
    return {
      total: latestYear?.total_co2e || 0,
      scope1: latestYear?.scope_1 || 0,
      scope2: latestYear?.scope_2 || 0,
      scope3: latestYear?.scope_3 || 0,
    };
  }, [sortedMonthlyEmissions, summary]);

  const displayScopes = useMemo(() => {
    if (!summary) {
      return [];
    }

    const totalsByCode: Record<ScopeBreakdown['code'], number> = {
      S1: activeYearTotals.scope1,
      S2: activeYearTotals.scope2,
      S3: activeYearTotals.scope3,
    };

    return summary.scope_breakdown.map((scope) => ({
      ...scope,
      total_co2e: totalsByCode[scope.code],
      percentage: activeYearTotals.total ? Number(((totalsByCode[scope.code] / activeYearTotals.total) * 100).toFixed(2)) : 0,
    }));
  }, [activeYearTotals, summary]);

  const chartData = useMemo(() => {
    return sortedMonthlyEmissions.map((item) => ({
      label: `${item.month_name.slice(0, 3)} ${String(item.year).slice(-2)}`,
      scope1: item.scope_1,
      scope2: item.scope_2,
      scope3: item.scope_3,
    }));
  }, [sortedMonthlyEmissions]);

  if (isLoading) {
    return <div className="rounded-3xl border border-slate-200 bg-white p-8 text-sm text-slate-500">Loading emissions analytics...</div>;
  }

  if (error || !summary) {
    return <div className="rounded-3xl border border-rose-200 bg-rose-50 p-8 text-sm text-rose-700">{error || 'No emissions data available.'}</div>;
  }

  return (
    <div>
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Emissions Analysis</h1>
          <p className="mt-2 text-sm text-slate-600">Monthly-wise Emission Trend.</p> 
        </div>

        <div className="flex flex-wrap gap-3">
          <label className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm">
            <Filter className="h-4 w-4 text-slate-500" />
            <span className="text-slate-500">Year</span>
            <select
              value={selectedYear}
              onChange={(event) => {
                const value = event.target.value;
                setSelectedYear(value === 'all' ? 'all' : Number(value));
              }}
              className="bg-transparent font-medium text-slate-900 outline-none"
            >
              <option value="all">All years</option>
              {availableYears.map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <div className="rounded-3xl border border-teal-200 bg-gradient-to-br from-teal-50 to-white p-5 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="rounded-2xl bg-teal-100 p-3 text-teal-700">
              <Activity className="h-5 w-5" />
            </div>
            <div>
              <p className="text-sm text-slate-500">Total emissions</p>
              <p className="text-3xl font-semibold text-slate-900">{formatNumber(activeYearTotals.total)}</p>
            </div>
          </div>
          <p className="mt-4 text-xs font-medium text-teal-700">{toTrend(summary, 'total_co2e')}% vs previous year</p>
        </div>

        {displayScopes.map((scope) => {
          const Icon = scopeIcon(scope.code);
          return (
            <div key={scope.code} className={`rounded-3xl border bg-gradient-to-br p-5 shadow-sm ${scopeCardStyles(scope.code)}`}>
              <div className="flex items-center gap-3">
                <div className="rounded-2xl bg-white/80 p-3 text-slate-700">
                  <Icon className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-sm text-slate-500">{scope.label}</p>
                  <p className="text-3xl font-semibold text-slate-900">{formatNumber(scope.total_co2e)}</p>
                </div>
              </div>
              <p className="mt-4 text-xs font-medium text-slate-600">{scope.percentage}% of total footprint</p>
            </div>
          );
        })}
      </div>

      <div className="mt-6">
        <EmissionsLineChart
          data={chartData}
          xAxisKey="label"
          title={selectedYear === 'all' ? 'Portfolio monthly emissions' : `${selectedYear} monthly emissions`}
          description="Scope totals for the selected reporting year."
        />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(320px,0.9fr)]">
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-slate-900">Scope-wise breakdown</h3>
          <p className="mt-1 text-sm text-slate-500">Hover cards on the dashboard for quick detail, or use this full breakdown for deeper review.</p>

          <div className="mt-5 space-y-5">
            {displayScopes.map((scope) => (
              <div key={scope.code} className="rounded-2xl border border-slate-200 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">{scope.label}</p>
                    <p className="text-xs text-slate-500">{formatNumber(scope.total_co2e)} tCO2e | {scope.percentage}% share</p>
                  </div>
                </div>

                <div className="mt-4 space-y-2">
                  {scope.breakdown.map((item) => (
                    <div key={`${scope.code}-${item.category}-${item.subcategory}`} className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3">
                      <div>
                        <p className="text-sm font-medium text-slate-900">{item.subcategory || item.category || 'Unspecified source'}</p>
                        <p className="text-xs text-slate-500">
                          {[item.category, item.scope3_category, item.gas_type].filter(Boolean).join(' | ') || 'No secondary classification'}
                        </p>
                      </div>
                      <span className="text-sm font-semibold text-slate-900">{formatNumber(item.total_co2e)} tCO2e</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="grid gap-6">
          <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Selected-year highlights</h3>
            <div className="mt-4 space-y-3 text-sm">
              <div className="rounded-2xl bg-slate-50 px-4 py-3">
                <p className="text-slate-500">Approved activities</p>
                <p className="mt-1 font-semibold text-slate-900">{summary.kpis.approved_activities}</p>
              </div>
              <div className="rounded-2xl bg-slate-50 px-4 py-3">
                <p className="text-slate-500">Top scope</p>
                <p className="mt-1 font-semibold text-slate-900">{summary.highlights.top_emission_scope.label || 'Unknown'}</p>
              </div>
              <div className="rounded-2xl bg-slate-50 px-4 py-3">
                <p className="text-slate-500">Latest month total</p>
                <p className="mt-1 font-semibold text-slate-900">
                  {summary.highlights.latest_month ? `${formatNumber(summary.highlights.latest_month.total_co2e)} tCO2e` : 'Not available'}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
