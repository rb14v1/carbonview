import { useEffect, useState } from 'react';
import { Download, FileText, TrendingDown, TrendingUp } from 'lucide-react';
import { DashboardSummaryResponse, MonthlyEmissionSeriesPoint, exportEsgReportExcel, fetchDashboardSummary } from '../../api';

type ReportType = 'all' | 'quarterly' | 'annual';

type DerivedReport = {
  id: string;
  title: string;
  date: string;
  type: 'Quarterly' | 'Annual';
  emissions: number;
  reduction: number;
};

type ExportScope = {
  organization?: number | null;
  facility?: number | null;
};

function formatQuarterEndDate(year: number, quarter: number) {
  const endMonth = quarter * 3;
  return new Date(year, endMonth, 0).toISOString();
}

function formatAnnualEndDate(year: number) {
  return new Date(year, 11, 31).toISOString();
}

function calculateReduction(current: number, previous: number | undefined) {
  if (!previous || previous === 0) return 0;
  return Number((((current - previous) / previous) * 100).toFixed(1));
}

function isFutureMonthlyPoint(entry: MonthlyEmissionSeriesPoint, currentDate: Date) {
  const entryDate = new Date(entry.year, entry.month - 1, 1);
  const currentMonth = new Date(currentDate.getFullYear(), currentDate.getMonth(), 1);
  return entryDate.getTime() > currentMonth.getTime();
}

function getAvailableExportPeriods(summary: DashboardSummaryResponse | null) {
  if (!summary) {
    return [];
  }

  const currentDate = new Date();
  const uniquePeriods = new Map<string, { year: number; month: number; label: string }>();

  summary.monthly_emissions
    .filter((entry) => !isFutureMonthlyPoint(entry, currentDate))
    .forEach((entry) => {
      const key = `${entry.year}-${entry.month}`;
      if (!uniquePeriods.has(key)) {
        uniquePeriods.set(key, {
          year: entry.year,
          month: entry.month,
          label: `${entry.month_name} ${entry.year}`,
        });
      }
    });

  return Array.from(uniquePeriods.values()).sort((a, b) => {
    if (a.year !== b.year) {
      return b.year - a.year;
    }
    return b.month - a.month;
  });
}

function comparePeriods(yearA: number, monthA: number, yearB: number, monthB: number) {
  if (yearA !== yearB) {
    return yearA - yearB;
  }
  return monthA - monthB;
}

function buildReports(summary: DashboardSummaryResponse) {
  const currentDate = new Date();
  const currentYear = currentDate.getFullYear();
  const filteredMonthlyEntries = summary.monthly_emissions.filter((entry) => !isFutureMonthlyPoint(entry, currentDate));
  const quarterlyMap = new Map<string, { year: number; quarter: number; emissions: number }>();

  filteredMonthlyEntries.forEach((entry: MonthlyEmissionSeriesPoint) => {
    const quarter = Math.ceil(entry.month / 3);
    const key = `${entry.year}-Q${quarter}`;
    const existing = quarterlyMap.get(key);

    if (existing) {
      existing.emissions += entry.total_co2e;
    } else {
      quarterlyMap.set(key, {
        year: entry.year,
        quarter,
        emissions: entry.total_co2e,
      });
    }
  });

  const quarterlyEntries = Array.from(quarterlyMap.values()).sort((a, b) => {
    if (a.year !== b.year) return b.year - a.year;
    return b.quarter - a.quarter;
  });

  const quarterlyReports: DerivedReport[] = quarterlyEntries.map((entry, index) => {
    const previous = quarterlyEntries[index + 1];
    return {
      id: `quarterly-${entry.year}-Q${entry.quarter}`,
      title: `Q${entry.quarter} ${entry.year} Sustainability Report`,
      date:
        entry.year === currentYear && entry.quarter === Math.ceil((currentDate.getMonth() + 1) / 3)
          ? currentDate.toISOString()
          : formatQuarterEndDate(entry.year, entry.quarter),
      type: 'Quarterly',
      emissions: Number(entry.emissions.toFixed(2)),
      reduction: calculateReduction(entry.emissions, previous?.emissions),
    };
  });
  // Count available monthly points per year (exclude future months)
  const monthsByYear = new Map<number, Set<number>>();
  filteredMonthlyEntries.forEach((m) => {
    const set = monthsByYear.get(m.year) || new Set<number>();
    set.add(m.month);
    monthsByYear.set(m.year, set);
  });

  // Annual reports: include a year's annual report only when we have all 12 months for that year
  const annualReports: DerivedReport[] = [...summary.yearly_emissions]
    .sort((a, b) => b.year - a.year)
    .filter((entry) => {
      const months = monthsByYear.get(entry.year);
      return months && months.size >= 12;
    })
    .map((entry, index, source) => {
      const previous = source[index + 1];
      return {
        id: `annual-${entry.year}`,
        title: `Annual Carbon Footprint ${entry.year}`,
        date: formatAnnualEndDate(entry.year),
        type: 'Annual',
        emissions: Number(entry.total_co2e.toFixed(2)),
        reduction: calculateReduction(entry.total_co2e, previous?.total_co2e),
      };
    });

  // For the current year, keep quarterly reports only (up to current quarter) unless we have full 12 months
  const currentYearQuarterly = quarterlyReports.filter((q) => q.id.startsWith(`quarterly-${currentYear}-`));

  // If the current year has full 12 months, include its annual report as well
  const includeCurrentYearAnnual = (() => {
    const months = monthsByYear.get(currentYear);
    return months && months.size >= 12;
  })();

  const currentYearAnnual = includeCurrentYearAnnual
    ? [...summary.yearly_emissions].find((y) => y.year === currentYear)
    : null;

  const currentAnnualReportObj: DerivedReport[] = currentYearAnnual
    ? [
        {
          id: `annual-${currentYearAnnual.year}`,
          title: `Annual Carbon Footprint ${currentYearAnnual.year}`,
          date: formatAnnualEndDate(currentYearAnnual.year),
          type: 'Annual',
          emissions: Number(currentYearAnnual.total_co2e.toFixed(2)),
          reduction: 0,
        },
      ]
    : [];

  return [...annualReports, ...currentAnnualReportObj, ...currentYearQuarterly].sort(
    (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime(),
  );
}

async function downloadReport(report: DerivedReport, scope: ExportScope = {}) {
  // Determine start/end dates for the report
  let startDate = '';
  let endDate = '';

  if (report.type === 'Annual') {
    const year = Number(report.id.split('-')[1]);
    startDate = `${year}-01-01`;
    endDate = `${year}-12-31`;
  } else if (report.type === 'Quarterly') {
    // id format: quarterly-YYYY-Qn
    const parts = report.id.split('-');
    const year = Number(parts[1]);
    const qPart = parts[2];
    const quarter = Number(qPart.replace(/^Q/, ''));
    const startMonth = (quarter - 1) * 3 + 1;
    const endMonth = quarter * 3;
    startDate = `${year}-${String(startMonth).padStart(2, '0')}-01`;
    // compute last day of endMonth
    const lastDay = new Date(year, endMonth, 0).getDate();
    endDate = `${year}-${String(endMonth).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;
  } else {
    // fallback to current year
    const today = new Date();
    startDate = `${today.getFullYear()}-01-01`;
    endDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  }

  try {
    const resp = await exportEsgReportExcel({
      start_date: startDate,
      end_date: endDate,
      organization: scope.organization,
      facility: scope.facility,
    });
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = getDownloadFilename(resp, startDate, endDate);
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error('REPORT DOWNLOAD ERROR:', err);
    alert('Unable to download report. Try the Export in Excel feature with a custom date range.');
  }
}

function getDownloadFilename(response: Response, fallbackStartDate: string, fallbackEndDate: string) {
  const disposition = response.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="([^"]+)"/i);
  return match?.[1] || `esg_report_${fallbackStartDate}_to_${fallbackEndDate}.xlsx`;
}

export function ReportsView() {
  const [reportType, setReportType] = useState<ReportType>('all');
  const [reports, setReports] = useState<DerivedReport[]>([]);
  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [startYear, setStartYear] = useState('');
  const [startMonth, setStartMonth] = useState('');
  const [endYear, setEndYear] = useState('');
  const [endMonth, setEndMonth] = useState('');
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState('');

  const availablePeriods = getAvailableExportPeriods(summary);
  const availableYears = Array.from(new Set(availablePeriods.map((period) => period.year)));
  const monthsForStartYear = availablePeriods.filter((period) => String(period.year) === startYear);
  const monthsForEndYear = availablePeriods.filter((period) => String(period.year) === endYear);
  const exportScope: ExportScope = {
    organization: summary?.filters.organization_id ?? undefined,
    facility: summary?.filters.facility_id ?? undefined,
  };

  useEffect(() => {
    fetchDashboardSummary()
      .then((response) => {
        setSummary(response);
        setReports(buildReports(response));
        const periods = getAvailableExportPeriods(response);
        const latestPeriod = periods[0];
        const earliestPeriod = periods[periods.length - 1];
        if (earliestPeriod) {
          setStartYear(String(earliestPeriod.year));
          setStartMonth(String(earliestPeriod.month));
        }
        if (latestPeriod) {
          setEndYear(String(latestPeriod.year));
          setEndMonth(String(latestPeriod.month));
        }
        setError('');
      })
      .catch((err) => {
        console.error('REPORTS API ERROR:', err);
        setReports([]);
        setError('Unable to load report data right now.');
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!startYear || monthsForStartYear.some((period) => String(period.month) === startMonth)) {
      return;
    }

    const firstMonth = monthsForStartYear[0];
    setStartMonth(firstMonth ? String(firstMonth.month) : '');
  }, [monthsForStartYear, startMonth, startYear]);

  useEffect(() => {
    if (!endYear || monthsForEndYear.some((period) => String(period.month) === endMonth)) {
      return;
    }

    const firstMonth = monthsForEndYear[0];
    setEndMonth(firstMonth ? String(firstMonth.month) : '');
  }, [endMonth, endYear, monthsForEndYear]);

  const filteredReports = reports.filter((report) => {
    if (reportType === 'all') return true;
    return report.type.toLowerCase() === reportType;
  });

  async function handleExportExcel() {
    if (!startYear || !startMonth || !endYear || !endMonth) {
      setExportError('Please select both start and end month ranges.');
      return;
    }

    const startYearValue = Number(startYear);
    const startMonthValue = Number(startMonth);
    const endYearValue = Number(endYear);
    const endMonthValue = Number(endMonth);
    const startDate = `${startYearValue}-${String(startMonthValue).padStart(2, '0')}-01`;
    const lastDay = new Date(endYearValue, endMonthValue, 0).getDate();
    const endDate = `${endYearValue}-${String(endMonthValue).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;

    if (comparePeriods(startYearValue, startMonthValue, endYearValue, endMonthValue) > 0) {
      setExportError('Start month must be earlier than or equal to end month.');
      return;
    }

    try {
      setIsExporting(true);
      setExportError('');

      const response = await exportEsgReportExcel({
        start_date: startDate,
        end_date: endDate,
        organization: exportScope.organization,
        facility: exportScope.facility,
      });

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = getDownloadFilename(response, startDate, endDate);
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('REPORT EXPORT ERROR:', err);
      setExportError(err instanceof Error ? err.message : 'Unable to export the Excel report right now.');
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div>
      <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Reports & Analytics</h1>
          <p className="mt-2 text-sm text-slate-600">Annual and quarterly reports.</p>
        </div>
        {summary && (
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm">
            <span className="text-slate-500">Coverage</span>
            <span className="ml-2 font-semibold text-slate-900">
              {summary.monthly_emissions.length} monthly data points across {summary.yearly_emissions.length} years
            </span>
          </div>
        )}
      </div>

      <div className="mb-6 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-xl">
            <h2 className="text-base font-semibold text-slate-900">Export in Excel</h2>
            <p className="mt-1 text-sm text-slate-600">Choose a month range and download the ESG report as an Excel sheet.</p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[220px_220px_auto] lg:items-end">
            <div>
              <p className="mb-2 text-sm font-medium text-slate-700">Start month</p>
              <div className="grid grid-cols-2 gap-2">
                <select
                  value={startMonth}
                  onChange={(event) => setStartMonth(event.target.value)}
                  disabled={!startYear}
                  className="rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition-colors focus:border-emerald-500 disabled:bg-slate-100 disabled:text-slate-400"
                >
                  <option value="">Month</option>
                  {monthsForStartYear.map((period) => (
                    <option key={`start-month-${period.year}-${period.month}`} value={period.month}>
                      {period.label.split(' ')[0]}
                    </option>
                  ))}
                </select>

                <select
                  value={startYear}
                  onChange={(event) => setStartYear(event.target.value)}
                  className="rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition-colors focus:border-emerald-500"
                >
                  <option value="">Year</option>
                  {availableYears.map((year) => (
                    <option key={`start-year-${year}`} value={year}>
                      {year}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <p className="mb-2 text-sm font-medium text-slate-700">End month</p>
              <div className="grid grid-cols-2 gap-2">
                <select
                  value={endMonth}
                  onChange={(event) => setEndMonth(event.target.value)}
                  disabled={!endYear}
                  className="rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition-colors focus:border-emerald-500 disabled:bg-slate-100 disabled:text-slate-400"
                >
                  <option value="">Month</option>
                  {monthsForEndYear.map((period) => (
                    <option key={`end-month-${period.year}-${period.month}`} value={period.month}>
                      {period.label.split(' ')[0]}
                    </option>
                  ))}
                </select>

                <select
                  value={endYear}
                  onChange={(event) => setEndYear(event.target.value)}
                  className="rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition-colors focus:border-emerald-500"
                >
                  <option value="">Year</option>
                  {availableYears.map((year) => (
                    <option key={`end-year-${year}`} value={year}>
                      {year}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <button
              onClick={handleExportExcel}
              disabled={isExporting}
              className="inline-flex items-center justify-center gap-2 rounded-[24px] bg-emerald-600 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-emerald-400"
            >
              <Download className="h-4 w-4" />
              {isExporting ? 'Exporting...' : 'Export in Excel'}
            </button>
          </div>
        </div>

        {exportError && (
          <p className="mt-3 text-sm text-rose-600">{exportError}</p>
        )}
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <button
          onClick={() => setReportType('all')}
          className={`rounded-3xl border-2 p-5 text-left transition-all ${
            reportType === 'all' ? 'border-emerald-500 bg-emerald-50' : 'border-slate-200 bg-white hover:border-slate-300'
          }`}
        >
          <div className="text-sm text-slate-500">All reports</div>
          <div className="mt-1 text-3xl font-semibold text-slate-900">{reports.length}</div>
        </button>

        <button
          onClick={() => setReportType('quarterly')}
          className={`rounded-3xl border-2 p-5 text-left transition-all ${
            reportType === 'quarterly' ? 'border-sky-500 bg-sky-50' : 'border-slate-200 bg-white hover:border-slate-300'
          }`}
        >
          <div className="text-sm text-slate-500">Quarterly</div>
          <div className="mt-1 text-3xl font-semibold text-slate-900">{reports.filter((r) => r.type === 'Quarterly').length}</div>
        </button>

        <button
          onClick={() => setReportType('annual')}
          className={`rounded-3xl border-2 p-5 text-left transition-all ${
            reportType === 'annual' ? 'border-amber-500 bg-amber-50' : 'border-slate-200 bg-white hover:border-slate-300'
          }`}
        >
          <div className="text-sm text-slate-500">Annual</div>
          <div className="mt-1 text-3xl font-semibold text-slate-900">{reports.filter((r) => r.type === 'Annual').length}</div>
        </button>
      </div>

      <div className="rounded-3xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Report name</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Date</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Type</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Emissions</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Change</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Download</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={6} className="px-6 py-10 text-center text-sm text-slate-500">
                    Loading reports from backend...
                  </td>
                </tr>
              )}

              {!isLoading && error && (
                <tr>
                  <td colSpan={6} className="px-6 py-10 text-center text-sm text-rose-600">
                    {error}
                  </td>
                </tr>
              )}

              {!isLoading && !error && filteredReports.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-6 py-10 text-center text-sm text-slate-500">
                    No reports available for this filter.
                  </td>
                </tr>
              )}

              {!isLoading && !error && filteredReports.map((report) => (
                <tr key={report.id} className="border-b border-slate-100 transition-colors hover:bg-slate-50">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-slate-400" />
                      <span className="text-sm font-medium text-slate-900">{report.title}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-sm text-slate-600">
                    {new Date(report.date).toLocaleDateString('en-US', {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })}
                  </td>
                  <td className="px-6 py-4">
                    <span className="rounded-full bg-sky-50 px-2 py-1 text-xs font-medium text-sky-700">{report.type}</span>
                  </td>
                  <td className="px-6 py-4 text-sm text-slate-900">{report.emissions.toLocaleString()} tons</td>
                  <td className="px-6 py-4">
                    <span className={`flex items-center gap-1 text-xs font-medium ${report.reduction <= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                      {report.reduction <= 0 ? <TrendingDown className="h-3 w-3" /> : <TrendingUp className="h-3 w-3" />}
                      {Math.abs(report.reduction)}%
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <button
                      onClick={() => downloadReport(report, exportScope)}
                      className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50"
                    >
                      <Download className="h-3.5 w-3.5" />
                      Download
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
