import { TrendingDown, TrendingUp, Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';
import { apiEndpoints } from '../api';

type MonthlySummaryApiItem = {
  year?: number;
  month?: number;
  scope?: string;
  total_co2e?: string;
};

type MonthlySummaryApiResponse = {
  results?: MonthlySummaryApiItem[];
};

type ForecastState = {
  nextMonth: number;
  total: number;
  trendPercent: number;
  latestMonthLabel: string;
  latestMonthTotal: number;
  insights: string[];
};
const RECENT_MONTHS = 3;
const DEFAULT_FORECAST: ForecastState = {
  nextMonth: 0,
  total: 0,
  trendPercent: 0,
  latestMonthLabel: 'No recent data',
  latestMonthTotal: 0,
  insights: ['Add more monthly records to unlock trend-based forecasting.'],
};

function formatMonthLabel(year: number, month: number) {
  return new Date(year, month - 1, 1).toLocaleString('default', {
    month: 'short',
    year: 'numeric',
  });
}

export function ForecastSection() {
  const [forecast, setForecast] = useState<ForecastState>(DEFAULT_FORECAST);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  useEffect(() => {
    let isMounted = true;

    fetch(apiEndpoints.monthlyEmissionSummaries)
      .then((res) => res.json())
      .then((res: MonthlySummaryApiResponse | MonthlySummaryApiItem[]) => {
        if (!isMounted) {
          return;
        }

        const results = Array.isArray(res) ? res : res.results || [];
        const monthlyTotals = new Map<string, { year: number; month: number; total: number }>();
        let overallTotal = 0;

        results.forEach((item) => {
          const year = Number(item.year);
          const month = Number(item.month);
          const value = parseFloat(item.total_co2e || '0');

          if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(value)) {
            return;
          }

          overallTotal += value;

          const key = `${year}-${String(month).padStart(2, '0')}`;
          const current = monthlyTotals.get(key);

          if (current) {
            current.total += value;
            return;
          }

          monthlyTotals.set(key, { year, month, total: value });
        });

        const sortedMonths = Array.from(monthlyTotals.values()).sort(
          (a, b) => new Date(a.year, a.month - 1).getTime() - new Date(b.year, b.month - 1).getTime(),
        );

        if (!sortedMonths.length) {
          setForecast(DEFAULT_FORECAST);
          setError(null);
          setIsLoading(false);
          return;
        }

        const latestMonth = sortedMonths[sortedMonths.length - 1];
        const recentMonths = sortedMonths.slice(-RECENT_MONTHS);
        const monthChanges: number[] = [];

        for (let index = 1; index < recentMonths.length; index += 1) {
          monthChanges.push(recentMonths[index].total - recentMonths[index - 1].total);
        }

        const averageMonthlyChange = monthChanges.length
          ? monthChanges.reduce((sum, change) => sum + change, 0) / monthChanges.length
          : 0;

        const forecastValue = Math.max(latestMonth.total + averageMonthlyChange, 0);
        const previousMonth = sortedMonths[sortedMonths.length - 2];
        const trendPercent = previousMonth && previousMonth.total > 0
          ? ((latestMonth.total - previousMonth.total) / previousMonth.total) * 100
          : 0;

        const insights = [
          `${recentMonths.length >= 2 ? 'Recent trend' : 'Current month'} ${averageMonthlyChange <= 0 ? 'suggests lower emissions next month.' : 'suggests emissions may rise next month.'}`,
        ];

        setForecast({
          nextMonth: Math.round(forecastValue),
          total: overallTotal,
          trendPercent,
          latestMonthLabel: formatMonthLabel(latestMonth.year, latestMonth.month),
          latestMonthTotal: latestMonth.total,
          insights,
        });
        setError(null);
        setIsLoading(false);
      })
      .catch((err) => {
        if (!isMounted) {
          return;
        }

        console.error('FORECAST API ERROR:', err);
        setError('Unable to load forecast data right now.');
        setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const isTrendDown = forecast.trendPercent <= 0;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-lg text-gray-900 mb-1">Emissions Forecast</h3>
          <p className="text-sm text-gray-500">Recent trend estimate</p>
        </div>
        <div className="p-2 bg-purple-100 rounded-lg">
          <Sparkles className="w-5 h-5 text-purple-600" />
        </div>
      </div>

      {isLoading ? (
        <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
          Loading forecast data...
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : (
        <>
          <div className="mb-4">
            <div className="grid grid-cols-1 gap-4">
              <div className="bg-gradient-to-br from-purple-50 to-blue-50 rounded-lg p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm text-gray-600">Next Month Estimate</div>
                    <div className="mt-1 flex items-baseline gap-2">
                      <span className="text-2xl font-semibold text-gray-900">{forecast.nextMonth}</span>
                      <span className="text-sm text-gray-500">tons CO2e</span>
                    </div>
                    <p className="text-xs text-gray-600 mt-2">Based on the last {RECENT_MONTHS} months</p>
                  </div>
                  <div>
                    <div className={`inline-flex items-center px-3 py-2 rounded-full text-sm font-medium ${isTrendDown ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'}`}>
                      {isTrendDown ? <TrendingDown className="w-4 h-4" /> : <TrendingUp className="w-4 h-4" />} 
                      <span className="ml-2">{Math.abs(forecast.trendPercent).toFixed(1)}%</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
                <h4 className="text-sm text-blue-900 mb-2 flex items-center gap-2">
                  <Sparkles className="w-4 h-4" />
                  Forecast Insights
                </h4>
                <ul className="space-y-1 text-xs text-blue-800">
                  <li>- Latest recorded month: {forecast.latestMonthLabel}</li>
                  <li>- Month-over-month change: {forecast.trendPercent >= 0 ? '+' : ''}{forecast.trendPercent.toFixed(1)}%</li>
                  <li>- Latest month total: {forecast.latestMonthTotal.toFixed(0)} tons CO2e</li>
                  {forecast.insights.map((insight) => (
                    <li key={insight}>- {insight}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
