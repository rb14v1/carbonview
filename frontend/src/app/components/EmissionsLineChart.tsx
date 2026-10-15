import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

type EmissionsLineChartProps = {
  data: any[];
  title?: string;
  description?: string;
  xAxisKey?: string;
};

export function EmissionsLineChart({
  data,
  title = 'Historical Emission Trends',
  description = 'Scope-by-scope carbon performance over time',
  xAxisKey = 'month',
}: EmissionsLineChartProps) {
  const formatYAxisTick = (value: number) => Number(value.toFixed(0)).toLocaleString();

  if (!data || data.length === 0) {
    return <p className="text-gray-500">No chart data available</p>;
  }

  return (
    <div className="bg-white rounded-3xl border border-slate-200 p-6 shadow-sm">
      <div className="mb-5">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <p className="mt-1 text-sm text-slate-500">{description}</p>
      </div>

      <ResponsiveContainer width="100%" height={340}>
        <LineChart data={data} margin={{ top: 12, right: 12, left: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="4 4" stroke="#d7e1ea" vertical={false} />
          <XAxis
            dataKey={xAxisKey}
            tick={{ fill: '#64748b', fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: '#64748b', fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            width={64}
            tickFormatter={formatYAxisTick}
          />
          <Tooltip
            formatter={(value: number) => [`${formatYAxisTick(value)} tCO2e`, '']}
            contentStyle={{
              borderRadius: '16px',
              border: '1px solid #e2e8f0',
              boxShadow: '0 18px 40px rgba(15, 23, 42, 0.08)',
            }}
          />
          <Legend verticalAlign="bottom" height={36} />

          <Line
            type="monotone"
            dataKey="scope1"
            stroke="#147d73"
            strokeWidth={3.5}
            dot={false}
            activeDot={{ r: 7, fill: '#ffffff', stroke: '#147d73', strokeWidth: 3 }}
            name="Scope 1"
          />
          <Line
            type="monotone"
            dataKey="scope2"
            stroke="#ee9808"
            strokeWidth={3.5}
            dot={false}
            activeDot={{ r: 7, fill: '#ffffff', stroke: '#ee9808', strokeWidth: 3 }}
            name="Scope 2"
          />
          <Line
            type="monotone"
            dataKey="scope3"
            stroke="#e11d48"
            strokeWidth={3.5}
            dot={false}
            activeDot={{ r: 7, fill: '#ffffff', stroke: '#e11d48', strokeWidth: 3 }}
            name="Scope 3"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
