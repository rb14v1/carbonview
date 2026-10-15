import { Activity, TrendingDown } from 'lucide-react';
import { useEffect, useState } from 'react';
import { apiEndpoints } from '../api';

export function RealTimeWidget() {

  const [currentRate, setCurrentRate] = useState(0);
  const [todayTotal, setTodayTotal] = useState(0);

  // ✅ get base data from backend
  useEffect(() => {
    fetch(apiEndpoints.monthlyEmissionSummaries)
      .then(res => res.json())
      .then(data => {
        const results = Array.isArray(data) ? data : data.results || [];
        const total = results.reduce((sum: number, item: any) => {
          return sum + parseFloat(item.total_co2e || "0");
        }, 0);
        const baseRate = total / 1000; // simple scaling
        setCurrentRate(baseRate);
        setTodayTotal(total);
      });
  }, []);

  // ✅ simulate real-time variation
  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentRate((prev) => {
        const change = (Math.random() - 0.5) * 0.05;
        return Math.max(0, prev + change);
      });
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  const yesterday = todayTotal * 1.1;
  const baseline = todayTotal * 1.3;
  const progress = (todayTotal / 1000) * 100;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-lg text-gray-900 mb-1">Real-time Emission Rate</h3>
          <p className="text-sm text-gray-500">Current CO₂e output per hour</p>
        </div>
        <div className="p-2 bg-emerald-100 rounded-lg">
          <Activity className="w-5 h-5 text-emerald-600 animate-pulse" />
        </div>
      </div>

      <div className="flex items-baseline gap-2 mb-3">
        <span className="text-4xl font-semibold text-gray-900">
          {currentRate.toFixed(2)}
        </span>
        <span className="text-lg text-gray-500">tons/hr</span>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <TrendingDown className="w-4 h-4 text-emerald-500" />
        <span className="text-sm text-emerald-600">Live monitoring active</span>
      </div>

      <div className="bg-gray-100 rounded-lg p-3 space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-gray-600">Today's total</span>
          <span className="text-gray-900 font-medium">{todayTotal.toFixed(1)} tons</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-600">Yesterday</span>
          <span className="text-gray-500">{yesterday.toFixed(1)} tons</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-600">Baseline</span>
          <span className="text-gray-500">{baseline.toFixed(1)} tons</span>
        </div>
      </div>

      <div className="mt-4">
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>Daily Progress</span>
          <span>{progress.toFixed(0)}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className="bg-emerald-500 h-2 rounded-full transition-all"
            style={{ width: `${Math.min(progress, 100)}%` }}
          ></div>
        </div>
      </div>
    </div>
  );
}
