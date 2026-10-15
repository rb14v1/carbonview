import L, { DivIcon } from 'leaflet';
import { MapPin } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { MapContainer, Marker, Popup, TileLayer, useMap } from 'react-leaflet';
import { FacilityLocation, fetchDashboardSummary } from '../api';

type MapLocation = FacilityLocation & {
  lat: number;
  lng: number;
  emissionsLabel: string;
  statusTone: 'success' | 'warning' | 'error';
  coordinateSource: 'stored' | 'geocoded';
};

type EmissionsMapProps = {
  locations?: FacilityLocation[];
  title?: string;
  description?: string;
  selectedFacilityId?: number | null;
  onSelectFacility?: (facilityId: number) => void;
  heightClassName?: string;
};

const geocodeCache = new Map<string, { lat: number; lng: number }>();

function getGeocodeKey(location: FacilityLocation) {
  return [location.city, location.state, location.country].filter(Boolean).join('|');
}

async function geocodeLocation(location: FacilityLocation) {
  const cacheKey = getGeocodeKey(location);

  if (!cacheKey) {
    return null;
  }

  if (geocodeCache.has(cacheKey)) {
    return geocodeCache.get(cacheKey)!;
  }

  const query = [location.city, location.state, location.country].filter(Boolean).join(', ');

  try {
    const response = await fetch(
      `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(query)}`,
      {
        headers: {
          Accept: 'application/json',
        },
      },
    );

    if (!response.ok) {
      return null;
    }

    const result = (await response.json()) as Array<{ lat: string; lon: string }>;
    const match = result[0];

    if (!match) {
      return null;
    }

    const coordinates = {
      lat: Number(match.lat),
      lng: Number(match.lon),
    };

    geocodeCache.set(cacheKey, coordinates);
    return coordinates;
  } catch (error) {
    console.error('MAP GEOCODING ERROR:', error);
    return null;
  }
}

function deriveStatusTone(location: FacilityLocation, index: number): MapLocation['statusTone'] {
  if (location.is_carbon_neutral) {
    return 'success';
  }

  if (!location.is_active) {
    return 'error';
  }

  return index % 2 === 0 ? 'warning' : 'success';
}

function createMarkerIcon(statusTone: MapLocation['statusTone'], isSelected: boolean) {
  const palette: Record<MapLocation['statusTone'], { dot: string; ring: string }> = {
    success: { dot: '#059669', ring: 'rgba(5, 150, 105, 0.22)' },
    warning: { dot: '#d97706', ring: 'rgba(217, 119, 6, 0.22)' },
    error: { dot: '#e11d48', ring: 'rgba(225, 29, 72, 0.22)' },
  };

  const theme = palette[statusTone];
  const coreSize = isSelected ? 20 : 16;
  const haloSize = isSelected ? 42 : 30;

  return new DivIcon({
    className: 'facility-map-marker',
    html: `
      <div style="position: relative; width: ${haloSize}px; height: ${haloSize}px; display: grid; place-items: center;">
        <span style="position: absolute; inset: 0; border-radius: 999px; background: ${theme.ring};"></span>
        <span style="position: relative; width: ${coreSize}px; height: ${coreSize}px; border-radius: 999px; background: ${theme.dot}; border: 3px solid white; box-shadow: 0 10px 20px rgba(15, 23, 42, 0.24);"></span>
      </div>
    `,
    iconSize: [haloSize, haloSize],
    iconAnchor: [haloSize / 2, haloSize / 2],
    popupAnchor: [0, -haloSize / 2],
  });
}

function FitMapBounds({ locations, selectedFacilityId }: { locations: MapLocation[]; selectedFacilityId?: number | null }) {
  const map = useMap();

  useEffect(() => {
    if (!locations.length) {
      return;
    }

    if (selectedFacilityId !== null && selectedFacilityId !== undefined) {
      const selected = locations.find((location) => location.facility_id === selectedFacilityId);
      if (selected) {
        map.flyTo([selected.lat, selected.lng], Math.max(map.getZoom(), 4), {
          animate: true,
          duration: 1.1,
        });
        return;
      }
    }

    const bounds = L.latLngBounds(locations.map((location) => [location.lat, location.lng]));
    map.fitBounds(bounds, {
      padding: [48, 48],
      animate: true,
      duration: 1.1,
    });
  }, [locations, map, selectedFacilityId]);

  return null;
}

export function EmissionsMap({
  locations: externalLocations,
  title = 'Emission Hotspots',
  description = 'Geographic distribution across reporting facilities',
  selectedFacilityId,
  onSelectFacility,
  heightClassName = 'h-[440px]',
}: EmissionsMapProps) {
  const [locations, setLocations] = useState<FacilityLocation[]>(externalLocations || []);
  const [resolvedCoordinates, setResolvedCoordinates] = useState<
    Record<number, { lat: number; lng: number; coordinateSource: MapLocation['coordinateSource'] } | null>
  >({});

  useEffect(() => {
    if (externalLocations) {
      setLocations(externalLocations);
      return;
    }

    fetchDashboardSummary()
      .then((summary) => {
        setLocations(summary.geo.facility_locations);
      })
      .catch((error) => {
        console.error('MAP API ERROR:', error);
        setLocations([]);
      });
  }, [externalLocations]);

  useEffect(() => {
    let cancelled = false;

    async function resolveAllCoordinates() {
      const entries = await Promise.all(
        locations.map(async (location) => {
          if (location.latitude !== null && location.longitude !== null) {
            return [
              location.facility_id,
              {
                lat: location.latitude,
                lng: location.longitude,
                coordinateSource: 'stored' as const,
              },
            ] as const;
          }

          const geocoded = await geocodeLocation(location);
          if (geocoded) {
            return [
              location.facility_id,
              {
                ...geocoded,
                coordinateSource: 'geocoded' as const,
              },
            ] as const;
          }

          return [
            location.facility_id,
            null,
          ] as const;
        }),
      );

      if (!cancelled) {
        setResolvedCoordinates(Object.fromEntries(entries));
      }
    }

    if (locations.length) {
      resolveAllCoordinates();
    } else {
      setResolvedCoordinates({});
    }

    return () => {
      cancelled = true;
    };
  }, [locations]);

  const mappedLocations = useMemo<MapLocation[]>(() => {
    return locations.flatMap((location, index) => {
      const coordinates = resolvedCoordinates[location.facility_id];
      if (!coordinates) {
        return [];
      }

      return [{
        ...location,
        lat: coordinates.lat,
        lng: coordinates.lng,
        emissionsLabel: location.is_carbon_neutral ? 'Carbon neutral' : location.is_active ? 'Operational facility' : 'Inactive facility',
        statusTone: deriveStatusTone(location, index),
        coordinateSource: coordinates.coordinateSource,
      }];
    });
  }, [locations, resolvedCoordinates]);

  if (!mappedLocations.length) {
    return (
      <div className="rounded-3xl border bg-white p-6">
        <p className="text-gray-500">No location data available</p>
      </div>
    );
  }

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <p className="text-sm text-slate-500">{description}</p>
      </div>

      <div className={`relative isolate overflow-hidden rounded-[28px] border border-slate-200 bg-slate-100 [&_.leaflet-bottom]:z-10 [&_.leaflet-control]:z-10 [&_.leaflet-pane]:z-0 [&_.leaflet-popup]:z-20 [&_.leaflet-top]:z-10 ${heightClassName}`}>
        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-24 bg-gradient-to-b from-white/75 to-transparent" />
        <MapContainer center={[20, 0]} zoom={2} minZoom={2} scrollWheelZoom className="relative z-0 h-full w-full" zoomControl={false} attributionControl={false}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          />
          <FitMapBounds locations={mappedLocations} selectedFacilityId={selectedFacilityId} />
          {mappedLocations.map((location) => (
            <Marker
              key={location.facility_id}
              position={[location.lat, location.lng]}
              icon={createMarkerIcon(location.statusTone, selectedFacilityId === location.facility_id)}
              eventHandlers={{
                click: () => onSelectFacility?.(location.facility_id),
              }}
            >
              <Popup>
                <div className="min-w-[220px] space-y-3">
                  <div className="flex items-start gap-2">
                    <MapPin className="mt-0.5 h-4 w-4 text-teal-700" />
                    <div>
                      <h4 className="text-sm font-semibold text-slate-900">{location.facility_name}</h4>
                      <p className="text-xs text-slate-500">
                        {[location.city, location.state, location.country].filter(Boolean).join(', ') || 'Location pending'}
                      </p>
                    </div>
                  </div>
                  <div className="rounded-2xl bg-slate-50 px-3 py-2 text-xs text-slate-700">
                    <p className="font-medium text-slate-900">{location.emissionsLabel}</p>
                    <p className="mt-1">{location.coordinateSource === 'stored' ? 'Using stored facility coordinates' : 'Geocoded from city and state'}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded-xl bg-slate-50 px-3 py-2">
                      <p className="text-slate-500">Facility code</p>
                      <p className="mt-1 font-medium text-slate-900">{location.facility_code || 'Pending'}</p>
                    </div>
                    <div className="rounded-xl bg-slate-50 px-3 py-2">
                      <p className="text-slate-500">Status</p>
                      <p className="mt-1 font-medium text-slate-900">
                        {location.is_active ? 'Operational' : 'Inactive'}
                        {location.is_carbon_neutral ? ' / Neutral' : ''}
                      </p>
                    </div>
                  </div>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-emerald-500" />
            <span>Carbon neutral / stable</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-amber-500" />
            <span>Operational facility</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-rose-500" />
            <span>Needs attention</span>
          </div>
        </div>

        <span>
          {mappedLocations.length} mapped facilities
          {locations.length > mappedLocations.length ? ` | ${locations.length - mappedLocations.length} unresolved` : ''}
        </span>
      </div>
    </div>
  );
}
