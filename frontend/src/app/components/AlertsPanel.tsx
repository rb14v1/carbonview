import { AlertTriangle, AlertCircle, Info, X } from 'lucide-react';
import { useState, useEffect } from 'react';
import { apiEndpoints } from '../api';

export function AlertsPanel() {

  const [alerts, setAlerts] = useState<any[]>([]);

  useEffect(() => {
    fetch(apiEndpoints.monthlyEmissionSummaries)
      .then(res => res.json())
      .then(res => {
        const results = res.results || [];

        let total = 0;
        let scope1 = 0;

        results.forEach((item: any) => {
          const value = parseFloat(item.total_co2e || "0");
          total += value;

          if (item.scope === "S1") {
            scope1 += value;
          }
        });

        const generatedAlerts: any[] = [];

        if (total > 5000) {
          generatedAlerts.push({
            id: '1',
            type: 'error',
            title: 'High Emissions Detected',
            message: `Total emissions reached ${total.toFixed(2)} tons`,
            time: 'Just now',
          });
        }

        if (scope1 > 2000) {
          generatedAlerts.push({
            id: '2',
            type: 'warning',
            title: 'Scope 1 Alert',
            message: `Scope 1 emissions high (${scope1.toFixed(2)})`,
            time: 'Just now',
          });
        }

        if (generatedAlerts.length === 0) {
          generatedAlerts.push({
            id: '3',
            type: 'info',
            title: 'System Stable',
            message: 'All emissions within safe limits',
            time: 'Just now',
          });
        }

        setAlerts(generatedAlerts);
      })
      .catch(err => console.error("ALERT API ERROR:", err));
  }, []);

  const dismissAlert = (id: string) => {
    setAlerts((prev) => prev.filter((alert) => alert.id !== id));
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg text-gray-900">Recent Alerts</h3>
        <span className="text-xs text-gray-500">{alerts.length} active</span>
      </div>

      <div className="space-y-3">
        {alerts.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <Info className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No active alerts</p>
          </div>
        ) : (
          alerts.map((alert) => {

            const config: any = {
              error: {
                icon: AlertCircle,
                bgColor: 'bg-red-50',
                borderColor: 'border-red-200',
                iconColor: 'text-red-600',
                textColor: 'text-red-900',
              },
              warning: {
                icon: AlertTriangle,
                bgColor: 'bg-amber-50',
                borderColor: 'border-amber-200',
                iconColor: 'text-amber-600',
                textColor: 'text-amber-900',
              },
              info: {
                icon: Info,
                bgColor: 'bg-blue-50',
                borderColor: 'border-blue-200',
                iconColor: 'text-blue-600',
                textColor: 'text-blue-900',
              },
            };

            const { icon: Icon, bgColor, borderColor, iconColor, textColor } = config[alert.type];

            return (
              <div
                key={alert.id}
                className={`${bgColor} ${borderColor} border rounded-lg p-3 relative group`}
              >
                <button
                  onClick={() => dismissAlert(alert.id)}
                  className="absolute top-2 right-2 p-1 hover:bg-white/50 rounded opacity-0 group-hover:opacity-100"
                >
                  <X className="w-3 h-3 text-gray-600" />
                </button>

                <div className="flex gap-3">
                  <Icon className={`w-5 h-5 ${iconColor} mt-0.5`} />
                  <div className="flex-1 pr-6">
                    <h4 className={`text-sm font-medium ${textColor} mb-1`}>
                      {alert.title}
                    </h4>
                    <p className="text-xs text-gray-600 mb-2">
                      {alert.message}
                    </p>
                    <span className="text-xs text-gray-500">{alert.time}</span>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {alerts.length > 0 && (
        <button className="w-full mt-4 text-sm text-emerald-600 hover:text-emerald-700">
          View All Alerts
        </button>
      )}
    </div>
  );
}
