import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { useEffect, useState } from "react";
import { apiEndpoints } from '../api';

export function DepartmentBarChart() {

  const [data, setData] = useState<any[]>([]);

  useEffect(() => {
    fetch(apiEndpoints.departments)
      .then(res => res.json())
      .then(apiData => {
        console.log("DEPARTMENTS API:", apiData);

        const results = apiData.results || [];

        // 🔥 Since backend doesn't give emission values,
        // we simulate for now (for UI demo)
        const formatted = results.map((item: any) => ({
          department: item.name,
          emissions: Math.floor(Math.random() * 500 + 100),
          target: Math.floor(Math.random() * 400 + 80)
        }));

        setData(formatted);
      })
      .catch(err => console.error("DEPARTMENT API ERROR:", err));
  }, []);

  // ✅ handle empty data
  if (!data || data.length === 0) {
    return (
      <div className="bg-white rounded-xl border p-6">
        <p className="text-gray-500">No department data available</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
      <div className="mb-4">
        <h3 className="text-lg text-gray-900 mb-1">
          Department-wise Emissions
        </h3>
        <p className="text-sm text-gray-500">
          Current emissions distribution by department
        </p>
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />

          <XAxis
            dataKey="department"
            stroke="#6b7280"
            tick={{ fill: '#6b7280', fontSize: 11 }}
            angle={-15}
            textAnchor="end"
            height={60}
          />

          <YAxis
            stroke="#6b7280"
            tick={{ fill: '#6b7280', fontSize: 12 }}
            label={{
              value: 'CO₂e (tons)',
              angle: -90,
              position: 'insideLeft',
              style: { fill: '#6b7280', fontSize: 12 }
            }}
          />

          <Tooltip
            contentStyle={{
              backgroundColor: 'white',
              border: '1px solid #e5e7eb',
              borderRadius: '8px',
              fontSize: '12px'
            }}
          />

          <Legend wrapperStyle={{ fontSize: '12px' }} />

          <Bar
            dataKey="emissions"
            fill="#10b981"
            radius={[8, 8, 0, 0]}
            name="Current Emissions"
          />

          <Bar
            dataKey="target"
            fill="#0ea5e9"
            radius={[8, 8, 0, 0]}
            name="Target"
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
