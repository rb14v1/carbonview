import { useState, useEffect, useRef } from 'react';
import { Bell, User, Menu, LogOut, Settings as SettingsIcon, UserCircle, X } from 'lucide-react';
import logo from '../../assets/version1-logo.svg';
import carbonViewLogo from '../../assets/carbonviewlogo.png';
import { DashboardSummaryResponse, fetchDashboardSummary } from '../api';

type HeaderNotification = {
  id: number;
  message: string;
  meta: string;
  unread: boolean;
};

function findScopeTotal(summary: DashboardSummaryResponse, code: 'S1' | 'S2' | 'S3') {
  return summary.scope_breakdown.find((scope) => scope.code === code);
}

interface HeaderProps {
  onMenuClick: () => void;
  onNavigateToSettings: () => void;
}

export function Header({ onMenuClick, onNavigateToSettings }: HeaderProps) {
  const [showNotifications, setShowNotifications] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [notifications, setNotifications] = useState<HeaderNotification[]>([]);
  const notificationsRef = useRef<HTMLDivElement | null>(null);
  const userMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fetchDashboardSummary()
      .then((summary) => {
        const latestMonthLabel = summary.highlights.latest_month
          ? `${summary.highlights.latest_month.month_name} ${summary.highlights.latest_month.year}`
          : summary.highlights.latest_year
            ? `Reporting year ${summary.highlights.latest_year.year}`
            : 'Reporting period unavailable';
        const scope1 = findScopeTotal(summary, 'S1');

        setNotifications([
          {
            id: 1,
            message: `Total emissions: ${summary.kpis.gross_emissions.toFixed(2)} tCO2e`,
            meta: latestMonthLabel,
            unread: true,
          },
          {
            id: 2,
            message: `Scope 1 emissions: ${(scope1?.total_co2e || 0).toFixed(2)} tCO2e`,
            meta: scope1 ? `${scope1.percentage}% of total footprint` : latestMonthLabel,
            unread: false,
          },
        ]);
      })
      .catch(err => console.error('HEADER API ERROR:', err));
  }, []);

  useEffect(() => {
    if (!showNotifications) {
      return;
    }

    setNotifications((current) =>
      current.map((notification) =>
        notification.unread ? { ...notification, unread: false } : notification,
      ),
    );
  }, [showNotifications]);

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      const target = event.target as Node;

      if (showNotifications && notificationsRef.current && !notificationsRef.current.contains(target)) {
        setShowNotifications(false);
      }

      if (showUserMenu && userMenuRef.current && !userMenuRef.current.contains(target)) {
        setShowUserMenu(false);
      }
    }

    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [showNotifications, showUserMenu]);

  const handleSettingsClick = () => {
    setShowUserMenu(false);
    onNavigateToSettings();
  };

  const handleDismissNotification = (notificationId: number) => {
    setNotifications((current) => current.filter((notification) => notification.id !== notificationId));
  };

  return (
    <header className="sticky top-0 z-[1000] border-b border-white/10 bg-[#052831] shadow-[0_10px_30px_rgba(5,40,49,0.22)]">
      <div className="mx-auto flex max-w-[1820px] items-center justify-between px-4 py-3 md:px-6 lg:px-6 xl:px-8">
        <div className="flex items-center gap-3">
          <button
            onClick={onMenuClick}
            className="rounded-xl border border-white/10 p-2 text-white transition-all hover:bg-white/10 lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>

          <div className="flex items-center gap-4 md:gap-6">
            <div className="flex h-12 w-[172px] shrink-0 items-center justify-start overflow-hidden">
              <img
                src={logo}
                alt="Version 1"
                className="h-full w-full object-contain object-left"
              />
            </div>
            <div className="hidden h-12 w-[104px] shrink-0 items-center justify-start overflow-visible sm:flex">
              <img
                src={carbonViewLogo}
                alt="CarbonView"
                className="h-full w-auto max-w-none origin-left scale-[1.4] object-contain"
              />
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div ref={notificationsRef} className="relative">
            <button
              onClick={() => {
                setShowNotifications((current) => !current);
                setShowUserMenu(false);
              }}
              className="relative rounded-xl border border-white/10 bg-white/5 p-2 text-white transition-all hover:-translate-y-0.5 hover:bg-white/10"
            >
              <Bell className="h-5 w-5" />

              {notifications.some((notification) => notification.unread) && (
                <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-red-500" />
              )}
            </button>

            {showNotifications && (
              <div className="absolute right-0 z-50 mt-2 w-80 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_24px_60px_rgba(15,23,42,0.16)] animate-in fade-in-0 zoom-in-95">
                <div className="border-b border-slate-200 px-4 py-3 text-sm font-semibold text-slate-900">Notifications</div>

                {notifications.length === 0 ? (
                  <div className="p-4 text-sm text-gray-500">
                    No notifications available
                  </div>
                ) : (
                  notifications.map((notification) => (
                    <div key={notification.id} className="border-b border-slate-100 px-4 py-3 text-sm transition-colors hover:bg-slate-50">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <p className="font-medium text-slate-900">{notification.message}</p>
                          <span className="mt-1 inline-block text-xs text-slate-500">{notification.meta}</span>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleDismissNotification(notification.id)}
                          className="rounded-lg p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                          aria-label="Dismiss notification"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>

          <div ref={userMenuRef} className="relative">
            <button
              onClick={() => {
                setShowUserMenu((current) => !current);
                setShowNotifications(false);
              }}
              className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-white transition-all hover:-translate-y-0.5 hover:bg-white/10"
            >
              <User className="h-5 w-5" />
              <span className="hidden text-sm font-medium text-white md:block">Admin</span>
            </button>

            {showUserMenu && (
              <div className="absolute right-0 mt-2 w-48 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_24px_60px_rgba(15,23,42,0.16)] animate-in fade-in-0 zoom-in-95">
                <button className="flex w-full items-center gap-2 px-4 py-3 text-sm text-slate-700 transition-colors hover:bg-slate-50">
                  <UserCircle className="h-4 w-4" /> Profile
                </button>
                <button
                  onClick={handleSettingsClick}
                  className="flex w-full items-center gap-2 px-4 py-3 text-sm text-slate-700 transition-colors hover:bg-slate-50"
                >
                  <SettingsIcon className="h-4 w-4" /> Settings
                </button>
                <button className="flex w-full items-center gap-2 px-4 py-3 text-sm text-red-600 transition-colors hover:bg-red-50">
                  <LogOut className="h-4 w-4" /> Logout
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
