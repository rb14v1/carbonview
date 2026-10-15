import { useEffect, useState } from 'react';
import { Droplets, Flame, Leaf, TrendingDown, Zap } from 'lucide-react';
import { KPICard } from '../KPICard';
import { EmissionsLineChart } from '../EmissionsLineChart';
import { EmissionsMap } from '../EmissionsMap';
import { ForecastSection } from '../ForecastSection';
import { DashboardSummaryResponse, ScopeBreakdown, fetchDashboardSummary } from '../../api';

function formatCompactNumber(value: number) {
  return Number(value.toFixed(1)).toLocaleString();
}

function formatPercent(value: number) {
  return Number(value.toFixed(1));
}

function formatNumber(value: number) {
  return Number(value.toFixed(1)).toLocaleString();
}

function shareOfTotal(value: number, total: number) {
  if (!total) {
    return 0;
  }

  return Number(((value / total) * 100).toFixed(2));
}

function findScope(summary: DashboardSummaryResponse, code: ScopeBreakdown['code']) {
  return summary.scope_breakdown.find((scope) => scope.code === code);
}

function formatScopeDetails(scope: ScopeBreakdown | undefined) {
  if (!scope) {
    return [];
  }

  const grouped = new Map<string, { label: string; subtitle?: string; total: number }>();

  scope.breakdown.forEach((item) => {
    const label = item.subcategory || item.scope3_category || item.category || 'Unspecified source';
    const subtitle = item.category || item.gas_type || undefined;
    const existing = grouped.get(label);

    if (existing) {
      existing.total += item.total_co2e;
      return;
    }

    grouped.set(label, {
      label,
      subtitle,
      total: item.total_co2e,
    });
  });

  return Array.from(grouped.values())
    .sort((a, b) => b.total - a.total)
    .map((item) => ({
      label: item.label,
      subtitle: item.subtitle,
      value: `${formatNumber(item.total)} tCO2e`,
    }));
}

function calculateProjectCompletion(expected: number, actual: number) {
  if (!expected) {
    return 0;
  }

  return Math.min((actual / expected) * 100, 100);
}

export function DashboardView() {
  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchDashboardSummary()
      .then((response) => {
        setSummary(response);
        setError('');
      })
      .catch((err) => {
        console.error('DASHBOARD API ERROR:', err);
        setError('Unable to load dashboard data right now.');
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  if (isLoading) {
    return <div className="rounded-3xl border border-slate-200 bg-white p-8 text-sm text-slate-500">Loading dashboard...</div>;
  }

  if (error || !summary) {
    return <div className="rounded-3xl border border-rose-200 bg-rose-50 p-8 text-sm text-rose-700">{error || 'No dashboard data available.'}</div>;
  }

  const latestMonth = summary.highlights.latest_month;
  const chartData = summary.yearly_emissions.map((item) => ({
    label:
      item.year === latestMonth?.year
        ? `${latestMonth.month_name.slice(0, 3)} '${String(item.year).slice(-2)}`
        : `Dec '${String(item.year).slice(-2)}`,
    scope1: item.scope_1,
    scope2: item.scope_2,
    scope3: item.scope_3,
  }));

  const peakMonth = summary.highlights.peak_month;
  const topScope = summary.highlights.top_emission_scope;
  const yoyChange = formatPercent(summary.highlights.year_over_year_change_percentage);
  const latestYear = summary.highlights.latest_year;
  const totalLatestYearShare = latestYear ? `${formatNumber(latestYear.total_co2e)} tCO2e | 100% share` : undefined;
  const scope1 = findScope(summary, 'S1');
  const scope2 = findScope(summary, 'S2');
  const scope3 = findScope(summary, 'S3');
  const totalScopeDetails = [
    scope1 && { label: scope1.label, subtitle: `${scope1.percentage}% of total footprint`, value: `${formatNumber(scope1.total_co2e)} tCO2e` },
    scope2 && { label: scope2.label, subtitle: `${scope2.percentage}% of total footprint`, value: `${formatNumber(scope2.total_co2e)} tCO2e` },
    scope3 && { label: scope3.label, subtitle: `${scope3.percentage}% of total footprint`, value: `${formatNumber(scope3.total_co2e)} tCO2e` },
  ].filter(Boolean) as Array<{ label: string; subtitle?: string; value: string }>;
  const scope1Summary = scope1 ? `${formatNumber(scope1.total_co2e)} tCO2e | ${scope1.percentage}% share` : undefined;
  const scope2Summary = scope2 ? `${formatNumber(scope2.total_co2e)} tCO2e | ${scope2.percentage}% share` : undefined;
  const scope3Summary = scope3 ? `${formatNumber(scope3.total_co2e)} tCO2e | ${scope3.percentage}% share` : undefined;
  const resourceCards = [
    {
      label: 'Energy',
      value: formatCompactNumber(summary.energy.total_energy),
      meta: summary.energy.units.join(', ') || 'units unavailable',
    },
    {
      label: 'Renewable energy',
      value: formatCompactNumber(summary.energy.renewable_energy),
      meta: `${summary.highlights.renewable_energy_share_percentage}% share`,
    },
    {
      label: 'Water usage',
      value: formatCompactNumber(summary.water.total_water_usage),
      meta: summary.water.units.join(', ') || 'units unavailable',
    },
    {
      label: 'Waste handled',
      value: formatCompactNumber(summary.waste.total_waste),
      meta: `Avg recycled ${summary.waste.average_recycled_percentage.toFixed(1)}%`,
    },
  ];
  const totalCreditsRetired = summary.carbon_credits.reduce((sum, credit) => sum + credit.quantity_tco2e, 0);

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Carbon Footprint Dashboard</h1>
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-4">
        <KPICard
          title="Total emissions"
          value={formatNumber(summary.kpis.gross_emissions)}
          unit="tCO2e"
          trend={yoyChange}
          trendDirection={yoyChange > 0 ? 'increase' : yoyChange < 0 ? 'decrease' : 'neutral'}
          trendLabel="vs previous year"
          status="success"
          icon={Flame}
          details={totalScopeDetails}
          detailTitle="Scope breakdown"
          detailSummary={totalLatestYearShare}
          hoverHint="Hover to inspect scope split"
        />
        <KPICard
          title="Scope 1"
          value={formatNumber(scope1?.total_co2e || 0)}
          unit="tCO2e"
          trend={scope1?.percentage || 0}
          trendDirection="neutral"
          trendDisplayValue={`${scope1?.percentage || 0}%`}
          trendLabel="of total footprint"
          status="success"
          icon={Flame}
          details={formatScopeDetails(scope1)}
          detailTitle="Scope 1"
          detailSummary={scope1Summary}
          hoverHint="Hover to inspect Scope 1 breakdown"
          showDetailTotal={false}
        />
        <KPICard
          title="Scope 2"
          value={formatNumber(scope2?.total_co2e || 0)}
          unit="tCO2e"
          trend={scope2?.percentage || 0}
          trendDirection="neutral"
          trendDisplayValue={`${scope2?.percentage || 0}%`}
          trendLabel="of total footprint"
          status="warning"
          icon={Zap}
          details={formatScopeDetails(scope2)}
          detailTitle="Scope 2"
          detailSummary={scope2Summary}
          hoverHint="Hover to inspect Scope 2 breakdown"
          showDetailTotal={false}
        />
        <KPICard
          title="Scope 3"
          value={formatNumber(scope3?.total_co2e || 0)}
          unit="tCO2e"
          trend={scope3?.percentage || 0}
          trendDirection="neutral"
          trendDisplayValue={`${scope3?.percentage || 0}%`}
          trendLabel="of total footprint"
          status="error"
          icon={TrendingDown}
          details={formatScopeDetails(scope3)}
          detailTitle="Scope 3"
          detailSummary={scope3Summary}
          hoverHint="Hover to inspect Scope 3 breakdown"
          showDetailTotal={false}
        />
      </div>

      <div className="mt-8 grid grid-cols-1 gap-6 min-[1180px]:grid-cols-[minmax(0,1.45fr)_minmax(280px,0.9fr)]">
        <EmissionsLineChart
          data={chartData}
          xAxisKey="label"
          title="Emissions trend"
          description="Yearly scope totals across reporting periods."
        />

        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-slate-500">Performance signals</p>
              <h3 className="mt-2 text-xl font-semibold text-slate-900">
                {yoyChange <= 0 ? 'Reduction momentum is holding.' : 'Emissions rose year over year.'}
              </h3>
            </div>
            <div className="rounded-2xl bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-900">{yoyChange.toFixed(1)}%</div>
          </div>

          <div className="mt-5 grid gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-slate-50 px-4 py-3">
              <span className="text-sm text-slate-600">Latest reporting month</span>
              <span className="font-semibold text-slate-900">{latestMonth ? `${latestMonth.month_name} ${latestMonth.year}` : 'Not available'}</span>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-slate-50 px-4 py-3">
              <span className="text-sm text-slate-600">Peak period</span>
              <span className="font-semibold text-slate-900">{peakMonth ? `${peakMonth.month_name} ${peakMonth.year}` : 'Not available'}</span>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-slate-50 px-4 py-3">
              <span className="text-sm text-slate-600">Top emission scope</span>
              <span className="font-semibold text-slate-900">{topScope.label || 'Unknown'}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-8">
        <EmissionsMap
          locations={summary.geo.facility_locations}
          title="Facility footprint map"
          description="Interactive facility geography sourced directly from the dashboard geo payload."
        />
      </div>

      <div className="mt-8 grid grid-cols-1 gap-6 min-[1180px]:grid-cols-12">
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm min-[1180px]:col-span-7">
          <div className="flex items-center gap-3">
            <div className="rounded-2xl bg-teal-100 p-3 text-teal-700">
              <Leaf className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-slate-900">Resource and transition snapshot</h3>
              <p className="text-sm text-slate-500">Energy, water, waste, and credits.</p>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2">
            {resourceCards.map((card) => (
              <div key={card.label} className="rounded-2xl border border-slate-100 bg-slate-50/90 p-4">
                <div className="flex items-center gap-2 text-slate-500">
                  {card.label === 'Water usage' ? <Droplets className="h-4 w-4" /> : null}
                  <p className="text-sm">{card.label}</p>
                </div>
                <p className="mt-2 text-2xl font-semibold text-slate-900">{card.value}</p>
                <p className="mt-1 text-xs text-slate-500">{card.meta}</p>
              </div>
            ))}
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-3">
            <div className="rounded-2xl border border-emerald-100 bg-emerald-50/70 px-4 py-3">
              <p className="text-xs uppercase tracking-wide text-emerald-700">Credits retired</p>
              <p className="mt-1 text-lg font-semibold text-slate-900">{formatCompactNumber(totalCreditsRetired)} tCO2e</p>
            </div>
            <div className="rounded-2xl border border-sky-100 bg-sky-50/70 px-4 py-3">
              <p className="text-xs uppercase tracking-wide text-sky-700">Projects tracked</p>
              <p className="mt-1 text-lg font-semibold text-slate-900">{summary.reduction_projects.length}</p>
            </div>
            <div className="rounded-2xl border border-amber-100 bg-amber-50/70 px-4 py-3">
              <p className="text-xs uppercase tracking-wide text-amber-700">Water categories</p>
              <p className="mt-1 text-lg font-semibold text-slate-900">{summary.water.categories.length}</p>
            </div>
          </div>
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm min-[1180px]:col-span-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-emerald-100 p-3 text-emerald-700">
                <Leaf className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-slate-900">Carbon credits</h3>
                <p className="text-sm text-slate-500">Retired credits</p>
              </div>
            </div>
            <div className="rounded-2xl bg-emerald-50 px-4 py-2 text-right">
              <p className="text-xs text-emerald-700">Total retired</p>
              <p className="text-sm font-semibold text-slate-900">{formatCompactNumber(totalCreditsRetired)} tCO2e</p>
            </div>
          </div>

            <div className="mt-5 grid max-h-[420px] gap-3 overflow-y-auto pr-2">
              {summary.carbon_credits.map((credit) => (
                <div key={credit.id} className="rounded-2xl border border-slate-200 bg-slate-50/50 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-semibold text-slate-900">{credit.project_name}</p>
                      <p className="mt-1 text-xs text-slate-500">{credit.registry_name}| {credit.status}</p>
                    </div>
                    <div className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-emerald-700">
                      {formatCompactNumber(credit.quantity_tco2e)} tCO2e
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm min-[1180px]:col-span-6">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-sky-100 p-3 text-sky-700">
                <TrendingDown className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-slate-900">Reduction projects</h3>
                <p className="text-sm text-slate-500">Expected and achieved reductions from active projects.</p>
              </div>
            </div>

            <div className="mt-5 grid gap-3">
              {summary.reduction_projects.slice(0, 3).map((project) => (
                <div key={project.id} className="rounded-2xl border border-slate-200 bg-slate-50/50 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <p className="text-sm font-semibold text-slate-900">{project.name}</p>
                    <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-sky-700">
                      {calculateProjectCompletion(project.expected_reduction_tco2e, project.actual_reduction_tco2e).toFixed(0)}%
                    </span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-xl bg-white px-3 py-3">
                      <p className="text-xs uppercase tracking-wide text-slate-400">Expected</p>
                      <p className="mt-1 font-semibold text-slate-900">{formatCompactNumber(project.expected_reduction_tco2e)} tCO2e</p>
                    </div>
                    <div className="rounded-xl bg-white px-3 py-3">
                      <p className="text-xs uppercase tracking-wide text-slate-400">Actual</p>
                      <p className="mt-1 font-semibold text-slate-900">{formatCompactNumber(project.actual_reduction_tco2e)} tCO2e</p>
                    </div>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-sky-500 to-teal-500"
                      style={{ width: `${calculateProjectCompletion(project.expected_reduction_tco2e, project.actual_reduction_tco2e)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="min-[1180px]:col-span-6">
            <ForecastSection />
          </div>
      </div>
    </>
  );
}
