import { useState } from 'react';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { AIChatbot } from './components/AIChatbot';
import { DashboardView } from './components/views/DashboardView';
import { EmissionsView } from './components/views/EmissionsView';
import { LocationsView } from './components/views/LocationsView';
import { ReportsView } from './components/views/ReportsView';
import { SettingsView } from './components/views/SettingsView';
import { AccreditationView } from './components/views/AccreditationView';
export type ViewType = 'home' | 'emissions' | 'locations' | 'reports' | 'accreditation' | 'settings';

export default function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [currentView, setCurrentView] = useState<ViewType>('home');

  const handleNavigate = (view: ViewType) => {
    setCurrentView(view);
    setIsSidebarOpen(false);
  };

  const renderView = () => {
    switch (currentView) {
      case 'home':
        return <DashboardView />;
      case 'emissions':
        return <EmissionsView />;
      case 'locations':
        return <LocationsView />;
      case 'reports':
        return <ReportsView />;
      case 'accreditation':
        return <AccreditationView />;
      case 'settings':
        return <SettingsView />;
      default:
        return <DashboardView />;
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Header
        onMenuClick={() => setIsSidebarOpen(true)}
        onNavigateToSettings={() => handleNavigate('settings')}
      />

      <div className="mx-auto flex w-full max-w-[1820px] gap-0 px-0 lg:px-3 xl:px-5">
        <Sidebar
          isOpen={isSidebarOpen}
          onClose={() => setIsSidebarOpen(false)}
          currentView={currentView}
          onNavigate={handleNavigate}
        />

        <main className="min-w-0 flex-1 px-4 py-5 md:px-6 md:py-6 lg:px-6 lg:py-8 xl:px-8">
          {renderView()}
        </main>
      </div>

      <AIChatbot />
    </div>
  );
}
