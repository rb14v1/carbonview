function trimTrailingSlash(value: string) {
  return value.endsWith('/') ? value.slice(0, -1) : value;
}

function resolveApiBaseUrl() {
  const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();

  if (rawBaseUrl) {
    if (rawBaseUrl.startsWith('http://') || rawBaseUrl.startsWith('https://')) {
      return trimTrailingSlash(rawBaseUrl);
    }

    if (rawBaseUrl.startsWith('/')) {
      return trimTrailingSlash(rawBaseUrl);
    }

    return `https://${trimTrailingSlash(rawBaseUrl)}`;
  }

  // Keep local development behavior unchanged while allowing production builds
  // to use VITE_API_BASE_URL.
  return import.meta.env.DEV ? 'http://127.0.0.1:8000' : '';
}

const API_BASE_URL = resolveApiBaseUrl();

function joinUrl(base: string, path: string) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;

  if (!base) {
    return normalizedPath;
  }

  const normalizedBase = trimTrailingSlash(base);
  return `${normalizedBase}${normalizedPath}`;
}

function buildQueryString(params: Record<string, string | number | null | undefined>) {
  const searchParams = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') {
      return;
    }

    searchParams.set(key, String(value));
  });

  const queryString = searchParams.toString();
  return queryString ? `?${queryString}` : '';
}

export type DashboardFilters = {
  organization_id?: number | null;
  facility_id?: number | null;
  reporting_period_id?: number | null;
  year?: number | null;
  month?: number | null;
};

export type ScopeBreakdownItem = {
  category: string | null;
  subcategory: string | null;
  scope3_category: string | null;
  gas_type: string | null;
  total_co2e: number;
};

export type ScopeBreakdown = {
  code: 'S1' | 'S2' | 'S3';
  label: string;
  total_co2e: number;
  percentage: number;
  breakdown: ScopeBreakdownItem[];
};

export type FacilityLocation = {
  facility_id: number;
  facility_name: string;
  facility_code: string | null;
  is_active: boolean;
  is_carbon_neutral: boolean;
  street_address: string | null;
  postal_code: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  latitude: number | null;
  longitude: number | null;
};

export type EmissionSeriesPoint = {
  year: number;
  total_co2e: number;
  scope_1: number;
  scope_2: number;
  scope_3: number;
};

export type MonthlyEmissionSeriesPoint = EmissionSeriesPoint & {
  month: number;
  month_name: string;
};

export type DashboardSummaryResponse = {
  filters: {
    organization_id: number | null;
    facility_id: number | null;
    reporting_period_id: number | null;
    year: number | null;
  };
  entity: {
    organization: {
      id: number;
      name: string;
      legal_name: string;
      industry_type: string;
      reporting_boundary: string;
      base_currency: string;
      base_year: number | null;
    } | null;
    facility: {
      id: number;
      name: string;
      facility_code: string | null;
      is_active: boolean;
      is_carbon_neutral: boolean;
      location: {
        street_address: string | null;
        postal_code: string | null;
        country: string | null;
        state: string | null;
        city: string | null;
        latitude: number | null;
        longitude: number | null;
      };
    } | null;
    reporting_period: {
      id: number;
      name: string;
      year: number;
      start_date: string;
      end_date: string;
    } | null;
  };
  geo: {
    current_location: FacilityLocation | null;
    facility_locations: FacilityLocation[];
    has_coordinates: boolean;
  };
  kpis: {
    gross_emissions: number;
    offsets: number;
    reductions: number;
    net_emissions: number;
    is_carbon_neutral: boolean;
    approved_activities: number;
    facilities_count: number;
    reporting_periods_count: number;
  };
  highlights: {
    top_emission_scope: {
      code: 'S1' | 'S2' | 'S3' | null;
      label: string | null;
      total_co2e: number;
    };
    latest_month: MonthlyEmissionSeriesPoint | null;
    peak_month: MonthlyEmissionSeriesPoint | null;
    latest_year: EmissionSeriesPoint | null;
    year_over_year_change_percentage: number;
    renewable_energy_share_percentage: number;
    water_to_waste_ratio: number;
    net_vs_gross_reduction_percentage: number;
    yearly_emissions: EmissionSeriesPoint[];
    monthly_emissions: MonthlyEmissionSeriesPoint[];
  };
  scope_breakdown: ScopeBreakdown[];
  scope2_split: {
    location_based: number;
    market_based: number;
  };
  yearly_emissions: EmissionSeriesPoint[];
  monthly_emissions: MonthlyEmissionSeriesPoint[];
  energy: {
    total_energy: number;
    renewable_energy: number;
    non_renewable_energy: number;
    units: string[];
  };
  water: {
    total_water_usage: number;
    units: string[];
    categories: {
      category: string;
      amount: number;
      unit: string | null;
    }[];
  };
  waste: {
    total_waste: number;
    hazardous: number;
    non_hazardous: number;
    average_recycled_percentage: number;
    units: string[];
  };
  carbon_credits: {
    id: number;
    project_name: string;
    source: string;
    registry_name: string;
    vintage_year: number;
    quantity_tco2e: number;
    status: string;
  }[];
  reduction_projects: {
    id: number;
    name: string;
    expected_reduction_tco2e: number;
    actual_reduction_tco2e: number;
  }[];
  neutrality_claims: {
    id: number;
    name: string;
    status: string;
    reporting_period: string;
    gross_emissions: number;
    reductions: number;
    offsets_retired: number;
    net_emissions: number;
  }[];
};

export const apiEndpoints = {
  ragAsk: joinUrl(API_BASE_URL, '/api/rag/ask/'),
  ragSuggestions: joinUrl(API_BASE_URL, '/api/rag/suggestions/'),
  facilities: joinUrl(API_BASE_URL, '/api/v1/org/facilities/'),
  departments: joinUrl(API_BASE_URL, '/api/v1/org/departments/'),
  monthlyEmissionSummaries: joinUrl(API_BASE_URL, '/api/v1/sum/monthly-emission-summaries/'),
  dashboardSummaries: joinUrl(API_BASE_URL, '/api/v1/sum/dashboard-summaries/'),
  certificates: joinUrl(API_BASE_URL, '/api/v1/sum/certificates/'),
  esgReportExcel: joinUrl(API_BASE_URL, '/api/v1/sum/esg-report/'),
};

export async function fetchDashboardSummary(filters: DashboardFilters = {}): Promise<DashboardSummaryResponse> {
  const response = await fetch(`${apiEndpoints.dashboardSummaries}${buildQueryString(filters)}`);

  if (!response.ok) {
    throw new Error(`Failed to load dashboard data (${response.status})`);
  }

  return response.json() as Promise<DashboardSummaryResponse>;
}

export async function exportEsgReportExcel(filters: {
  start_date: string;
  end_date: string;
  organization?: number | null;
  facility?: number | null;
}) {
  const response = await fetch(`${apiEndpoints.esgReportExcel}${buildQueryString(filters)}`);

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `Failed to export ESG report (${response.status})`);
  }

  return response;
}

export function toAbsoluteBackendUrl(url: string) {
  if (!url) return '';
  if (url.startsWith('http://') || url.startsWith('https://')) {
    return url;
  }

  return joinUrl(API_BASE_URL, url);
}
