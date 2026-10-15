import { BadgeCheck, Home, TrendingUp, MapPin, FileText, X } from 'lucide-react';

type ViewType = 'home' | 'emissions' | 'locations' | 'reports' | 'accreditation' | 'settings';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  currentView: ViewType;
  onNavigate: (view: ViewType) => void;
}

export function Sidebar({ isOpen, onClose, currentView, onNavigate }: SidebarProps) {
  const menuItems = [
    { id: 'home' as ViewType, label: 'Home', icon: Home },
    { id: 'emissions' as ViewType, label: 'Emissions', icon: TrendingUp },
    { id: 'locations' as ViewType, label: 'Locations', icon: MapPin },
    { id: 'reports' as ViewType, label: 'Reports', icon: FileText },
    { id: 'accreditation' as ViewType, label: 'Accreditation', icon: BadgeCheck },
  ];

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-[950] w-72 border-r border-slate-200 bg-white/95 shadow-[0_20px_60px_rgba(15,23,42,0.08)] backdrop-blur-xl transition-transform duration-300 lg:sticky lg:top-[73px] lg:h-[calc(100vh-73px)] lg:w-64 lg:rounded-r-3xl lg:border lg:border-l-0 lg:shadow-none ${
          isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="flex items-center justify-between border-b border-slate-200 p-5 lg:hidden">
          <span className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Menu</span>
          <button
            onClick={onClose}
            className="rounded-xl p-2 text-slate-700 transition-colors hover:bg-slate-100"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="space-y-2 p-4">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentView === item.id;

            return (
              <button
                key={item.id}
                onClick={() => onNavigate(item.id)}
                className={`flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left transition-all duration-200 ${
                  isActive
                    ? 'bg-teal-700 text-white shadow-[0_10px_24px_rgba(15,118,110,0.24)]'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                }`}
              >
                <div className={`rounded-xl p-2 ${isActive ? 'bg-white/15 text-white' : 'bg-slate-100 text-slate-500'}`}>
                  <Icon className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium">{item.label}</span>
              </button>
            );
          })}
        </nav>

      </aside>
    </>
  );
}
