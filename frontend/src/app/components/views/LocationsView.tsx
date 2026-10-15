import { useEffect, useMemo, useState } from 'react';
import { Building2, Globe2, MapPin, Search } from 'lucide-react';
import { EmissionsMap } from '../EmissionsMap';
import { DashboardSummaryResponse, FacilityLocation, fetchDashboardSummary } from '../../api';

function facilityLocationLabel(facility: FacilityLocation) {
  return [facility.city, facility.state, facility.country].filter(Boolean).join(', ') || 'Location pending';
}

export function LocationsView() {
  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null);
  const [selectedFacilityId, setSelectedFacilityId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    fetchDashboardSummary()
      .then((response) => {
        setSummary(response);
        setSelectedFacilityId(response.geo.facility_locations[0]?.facility_id ?? null);
        setError('');
      })
      .catch((err) => {
        console.error('LOCATIONS API ERROR:', err);
        setError('Unable to load facility locations right now.');
      });
  }, []);

  const facilities = summary?.geo.facility_locations || [];

  const filteredFacilities = useMemo(() => {
    return facilities.filter((facility) =>
      `${facility.facility_name} ${facilityLocationLabel(facility)} ${facility.facility_code || ''}`
        .toLowerCase()
        .includes(searchQuery.toLowerCase()),
    );
  }, [facilities, searchQuery]);

  const selectedFacility = facilities.find((facility) => facility.facility_id === selectedFacilityId) || facilities[0] || null;

  if (error) {
    return <div className="rounded-3xl border border-rose-200 bg-rose-50 p-8 text-sm text-rose-700">{error}</div>;
  }

  return (
    <div>
      <div className="mb-6 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Facility Locations</h1>
          <p className="mt-2 text-sm text-slate-600">Operational footprint across all facilities, with an interactive map.</p>
        </div>

        <div className="grid grid-cols-2 gap-3 rounded-3xl border border-slate-200 bg-white p-4 text-sm shadow-sm sm:grid-cols-3">
          <div>
            <p className="text-slate-500">Facilities</p>
            <p className="mt-1 font-semibold text-slate-900">{summary?.kpis.facilities_count ?? 0}</p>
          </div>
          <div>
            <p className="text-slate-500">Countries</p>
            <p className="mt-1 font-semibold text-slate-900">{new Set(facilities.map((item) => item.country).filter(Boolean)).size}</p>
          </div>
          <div>
            <p className="text-slate-500">Coordinate mode</p>
            <p className="mt-1 font-semibold text-slate-900">{summary?.geo.has_coordinates ? 'Stored + geocoded' : 'Geocoded from location fields'}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.6fr)_360px]">
        <EmissionsMap
          locations={facilities}
          selectedFacilityId={selectedFacilityId}
          onSelectFacility={setSelectedFacilityId}
          title="Global facility map"
          description="Stored coordinates are used first. If latitude and longitude are missing, the map geocodes city and state dynamically."
          heightClassName="h-[520px]"
        />

        <div className="space-y-6">
          <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
              <Search className="h-4 w-4 text-slate-400" />
              <input
                type="text"
                placeholder="Search facilities..."
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                className="w-full bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400"
              />
            </div>

            <div className="mt-4 max-h-[380px] space-y-3 overflow-auto pr-1">
              {filteredFacilities.map((facility) => (
                <button
                  key={facility.facility_id}
                  onClick={() => setSelectedFacilityId(facility.facility_id)}
                  className={`w-full rounded-2xl border p-4 text-left transition-all ${
                    selectedFacility?.facility_id === facility.facility_id
                      ? 'border-teal-300 bg-teal-50'
                      : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-900">{facility.facility_name}</p>
                      <p className="mt-1 text-xs text-slate-500">{facilityLocationLabel(facility)}</p>
                    </div>
                    <span
                      className={`rounded-full px-2 py-1 text-[11px] font-semibold uppercase tracking-wide ${
                        facility.is_carbon_neutral ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'
                      }`}
                    >
                      {facility.is_carbon_neutral ? 'Neutral' : facility.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                  <p className="mt-3 text-xs text-slate-500">{facility.facility_code || 'Code pending'}</p>
                </button>
              ))}

              {filteredFacilities.length === 0 && (
                <div className="rounded-2xl border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">
                  No facilities found for that search.
                </div>
              )}
            </div>
          </div>

          {selectedFacility && (
            <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-start gap-3">
                <div className="rounded-2xl bg-teal-100 p-3 text-teal-700">
                  <Building2 className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-slate-900">{selectedFacility.facility_name}</h3>
                  <p className="text-sm text-slate-500">{facilityLocationLabel(selectedFacility)}</p>
                </div>
              </div>

              <div className="mt-5 grid grid-cols-1 gap-3">
                <div className="rounded-2xl bg-slate-50 px-4 py-3">
                  <p className="text-xs uppercase tracking-wide text-slate-400">Address</p>
                  <p className="mt-1 text-sm text-slate-700">
                    {[selectedFacility.street_address, selectedFacility.postal_code].filter(Boolean).join(', ') || 'Address pending'}
                  </p>
                </div>
                <div className="rounded-2xl bg-slate-50 px-4 py-3">
                  <p className="text-xs uppercase tracking-wide text-slate-400">Facility code</p>
                  <p className="mt-1 text-sm font-medium text-slate-900">{selectedFacility.facility_code || 'Not assigned'}</p>
                </div>
                <div className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400">
                    <Globe2 className="h-3.5 w-3.5" />
                    Coordinate mode
                  </div>
                  <p className="mt-1 text-sm text-slate-700">
                    {selectedFacility.latitude !== null && selectedFacility.longitude !== null
                      ? 'Using stored facility coordinates'
                      : 'Map geocodes from city, state, and country when coordinates are missing'}
                  </p>
                </div>
                <div className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400">
                    <MapPin className="h-3.5 w-3.5" />
                    Status
                  </div>
                  <p className="mt-1 text-sm text-slate-700">
                    {selectedFacility.is_active ? 'Operational facility' : 'Inactive facility'}
                    {selectedFacility.is_carbon_neutral ? ' | Carbon neutral' : ''}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
