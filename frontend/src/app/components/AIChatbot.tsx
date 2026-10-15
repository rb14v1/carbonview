import { BarChart2, Lightbulb, MessageCircle, Send, Sparkles, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { DashboardFilters, apiEndpoints, fetchDashboardSummary } from '../api';
 
interface Message {
  id: string;
  type: 'user' | 'bot';
  content: string;
  tone?: 'default' | 'insight' | 'clarify';
  chart?: ChatChartPayload;
  explanation?: any;
  explanationOpen?: boolean;
}
 
interface RagResponse {
  answer?: string;
  error?: string;
  provider?: string;
  resolved_query?: string;
  route?: string;
  tool_output?: {
    chart?: ChatChartPayload;
  };
}
 
interface SuggestionsResponse {
  questions?: string[];
}
 
type ChatChartSeries = {
  name: string;
  data: number[];
};
 
type ChatChartPayload = {
  chart_type: 'line' | 'bar' | 'pie';
  title?: string;
  labels: string[];
  series: ChatChartSeries[];
  unit?: string;
  summary?: string;
};
 
const CHART_COLORS = ['#0f766e', '#2563eb', '#ea580c', '#dc2626', '#7c3aed'];
 
const GREETING_RESPONSES = [
  'Hi! I can help you explore emissions, facilities, reports, and sustainability insights. What would you like to know?',
  'Hello! I can help with emissions trends, facilities, reporting, and sustainability insights. What would you like to explore?',
];
 
function normalizeInput(value: string) {
  return value.trim().replace(/\s+/g, ' ');
}
 
function isGreeting(input: string) {
  return /^(hi|hello|hey|hey there|hi there|good morning|good afternoon|good evening)[!. ]*$/i.test(normalizeInput(input));
}
 
function getGreetingResponse(input: string) {
  return GREETING_RESPONSES[input.length % GREETING_RESPONSES.length];
}
 
function extractPreferredText(raw: string) {
  const trimmed = raw.trim();
 
  if (!trimmed) {
    return '';
  }
 
  const fencedMatch = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const content = fencedMatch?.[1]?.trim() || trimmed;
 
  if ((content.startsWith('{') && content.endsWith('}')) || (content.startsWith('[') && content.endsWith(']'))) {
    try {
      const parsed = JSON.parse(content);
 
      if (typeof parsed === 'string') {
        return parsed;
      }
 
      if (parsed && typeof parsed === 'object' && 'answer' in parsed && typeof parsed.answer === 'string') {
        return parsed.answer;
      }
 
      const flattened = flattenObject(parsed).slice(0, 6);
      if (flattened.length) {
        return flattened.join('. ');
      }
    } catch (error) {
      return content;
    }
  }
 
  return content;
}
 
function flattenObject(value: unknown, prefix = ''): string[] {
  if (value === null || value === undefined) {
    return [];
  }
 
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return [`${prefix}${value}`.trim()];
  }
 
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => flattenObject(item, prefix ? `${prefix}${index + 1}: ` : ''));
  }
 
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).flatMap(([key, nestedValue]) =>
      flattenObject(nestedValue, `${prefix}${key.replace(/_/g, ' ')}: `),
    );
  }
 
  return [];
}
 
function sentenceCase(input: string) {
  return input.charAt(0).toUpperCase() + input.slice(1);
}

function formatExplanationFilters(filters: any) {
  if (!filters || typeof filters !== 'object') {
    return [];
  }

  const scopes = Array.isArray(filters.scopes)
    ? filters.scopes
        .map((scope: string) => String(scope || '').trim())
        .filter(Boolean)
        .map((scope: string) => scope.replace(/^S(\d)$/i, 'Scope $1'))
    : [];
  const years = Array.isArray(filters.years) ? filters.years.filter(Boolean) : [];
  const monthYearPairs = Array.isArray(filters.month_year_pairs) ? filters.month_year_pairs.filter(Boolean) : [];
  const lines: string[] = [];

  if (filters.organization_id || filters.entities?.organization) {
    lines.push('Organization filter applied');
  }
  if (filters.facility_id || filters.entities?.facility) {
    lines.push('Facility filter applied');
  }
  if (filters.reporting_period_id || filters.entities?.reporting_period) {
    lines.push('Reporting period filter applied');
  }
  if (scopes.length) {
    lines.push(`Scope: ${scopes.join(', ')}`);
  }
  if (years.length) {
    lines.push(`Year${years.length > 1 ? 's' : ''}: ${years.join(', ')}`);
  }
  if (monthYearPairs.length) {
    const labels = monthYearPairs
      .map((pair: any) => (Array.isArray(pair) ? pair.join('-') : String(pair)))
      .filter(Boolean);
    if (labels.length) {
      lines.push(`Month${labels.length > 1 ? 's' : ''}: ${labels.join(', ')}`);
    }
  }

  return lines;
}

function formatRagAnswer(rawAnswer: string) {
  // remove any structural explainability token and trailing content
  const cleaned = rawAnswer.replace(/\[BUTTON:SHOW_EXPLANATION\][\s\S]*$/i, '').trim();
  const preferredText = extractPreferredText(cleaned).replace(/^[\s:-]+/, '').trim();
 
  if (!preferredText) {
    return 'I could not find a clean answer for that yet. Try asking for a specific year, metric, or facility.';
  }
 
  const lines = preferredText
    .split(/\n+/)
    .map((line) => line.replace(/^[*-]\s*/, '').trim())
    .filter(Boolean)
    .filter((line) => !/[{}[\]"]/.test(line));
 
  const sentenceSource = lines.join(' ');
  const sentences = sentenceSource
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
 
  return (sentences.length ? sentences : lines)
    .slice(0, 4)
    .map((sentence) => sentenceCase(sentence.replace(/\.+$/, '').trim()))
    .join('\n');
}
 
function shouldShowInsight(query: string) {
  const normalized = query.toLowerCase();
  return normalized.includes('trend') || normalized.includes('compare') || normalized.includes('show');
}
 
function ChatChart({ chart }: { chart: ChatChartPayload }) {
  const title = chart.title || 'Chart';
  const summary = chart.summary?.trim();
 
  if (chart.chart_type === 'pie') {
    const values = chart.series[0]?.data ?? [];
    const data = chart.labels.map((label, index) => ({
      name: label,
      value: values[index] ?? 0,
    }));
 
    if (!data.length) return null;
 
    return (
      <div className="mt-3 rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3">
          <h4 className="text-sm font-semibold text-slate-900">{title}</h4>
          {summary ? <p className="mt-1 text-xs text-slate-500">{summary}</p> : null}
        </div>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} dataKey="value" nameKey="name" outerRadius={84} innerRadius={42}>
                {data.map((entry, index) => (
                  <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip formatter={(value: number) => [`${value.toLocaleString()} ${chart.unit || ''}`.trim(), 'Value']} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }
 
  const data = chart.labels.map((label, index) => {
    const row: Record<string, string | number> = { label };
    chart.series.forEach((series) => {
      row[series.name] = series.data[index] ?? 0;
    });
    return row;
  });
 
  if (!data.length) return null;
 
  return (
    <div className="mt-3 rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3">
        <h4 className="text-sm font-semibold text-slate-900">{title}</h4>
        {summary ? <p className="mt-1 text-xs text-slate-500">{summary}</p> : null}
      </div>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {chart.chart_type === 'bar' ? (
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#dbe4ea" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip formatter={(value: number) => [`${value.toLocaleString()} ${chart.unit || ''}`.trim(), 'Value']} />
              <Legend />
              {chart.series.map((series, index) => (
                <Bar key={series.name} dataKey={series.name} fill={CHART_COLORS[index % CHART_COLORS.length]} radius={[8, 8, 0, 0]} />
              ))}
            </BarChart>
          ) : (
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#dbe4ea" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip formatter={(value: number) => [`${value.toLocaleString()} ${chart.unit || ''}`.trim(), 'Value']} />
              <Legend />
              {chart.series.map((series, index) => (
                <Line
                  key={series.name}
                  type="monotone"
                  dataKey={series.name}
                  stroke={CHART_COLORS[index % CHART_COLORS.length]}
                  strokeWidth={3}
                  dot={{ r: 3 }}
                  activeDot={{ r: 5 }}
                />
              ))}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
 
function formatFilterLabel(value: unknown) {
  if (value === null || value === undefined || value === '') {
    return 'All';
  }
 
  if (Array.isArray(value)) {
    return value.length ? value.join(', ') : 'All';
  }
 
  return String(value);
}
 
function humanizeDataSource(value: unknown) {
  const source = String(value || '').trim();
  const labels: Record<string, string> = {
    MonthlyEmissionSummary: 'monthly emissions summaries',
    EmissionActivity: 'approved emission activities',
    EmissionBreakdown: 'emissions breakdown records',
    EnergySummary: 'energy summaries',
    WaterUsage: 'water usage records',
    WasteSummary: 'waste summaries',
  };
 
  return labels[source] || source.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase() || 'CarbonView database records';
}
 
function buildExplanationSummary(sqlSource: any, appliedFilters: any) {
  const entities = appliedFilters.entities || {};
  const dimensions = appliedFilters.dimensions || {};
  const timeRange = appliedFilters.time_range || {};
  const organization = appliedFilters.organization_id ?? entities.organization;
  const facility = appliedFilters.facility_id ?? entities.facility;
  const reportingPeriod = appliedFilters.reporting_period_id ?? entities.reporting_period;
  const scopes = appliedFilters.scopes ?? dimensions.scopes;
  const years = appliedFilters.years ?? timeRange.years;
  const monthYearPairs = appliedFilters.month_year_pairs ?? timeRange.month_year_pairs;
  const parts = [`I used ${humanizeDataSource(sqlSource?.table)} from the CarbonView backend.`];
 
  if (organization) {
    parts.push('The result is limited to the selected organization.');
  }
 
  parts.push(facility ? 'It is filtered to the selected facility.' : 'It includes all facilities in that organization.');
 
  if (reportingPeriod) {
    parts.push('It uses the selected reporting period.');
  }
 
  if (scopes?.length) {
    parts.push(`It only includes ${formatFilterLabel(scopes)} data.`);
  }
 
  if (years?.length) {
    parts.push(`It is filtered to ${formatFilterLabel(years)}.`);
  }
 
  if (monthYearPairs?.length) {
    parts.push(`It uses the selected month/year filter.`);
  }
 
  return parts.join(' ');
}
 
function buildAppliedFilterRows(appliedFilters: any) {
  const rows: Array<{ label: string; value: string }> = [];
  const entities = appliedFilters.entities || {};
  const dimensions = appliedFilters.dimensions || {};
  const timeRange = appliedFilters.time_range || {};
  const organization = appliedFilters.organization_id ?? entities.organization;
  const facility = appliedFilters.facility_id ?? entities.facility;
  const reportingPeriod = appliedFilters.reporting_period_id ?? entities.reporting_period;
  const scopes = appliedFilters.scopes ?? dimensions.scopes;
  const years = appliedFilters.years ?? timeRange.years;
  const monthYearPairs = appliedFilters.month_year_pairs ?? timeRange.month_year_pairs;
 
  if (organization) {
    rows.push({ label: 'Organization', value: 'Selected organization' });
  }
 
  rows.push({ label: 'Facilities included', value: facility ? 'Selected facility' : 'All facilities' });
 
  if (reportingPeriod) {
    rows.push({ label: 'Reporting period', value: 'Selected reporting period' });
  }
 
  if (scopes?.length) {
    rows.push({ label: 'Scope', value: formatFilterLabel(scopes) });
  }
 
  if (years?.length) {
    rows.push({ label: 'Year', value: formatFilterLabel(years) });
  }
 
  if (monthYearPairs?.length) {
    rows.push({
      label: 'Month/year',
      value: monthYearPairs.map((pair: [number, number]) => `${pair[0]}-${String(pair[1]).padStart(2, '0')}`).join(', '),
    });
  }
 
  return rows;
}
 
function ExplanationPanel({ explanation }: { explanation: any }) {
  if (!explanation) return null;
 
  const sqlSource = explanation.sql_source || explanation.sqlSource || {};
  const appliedFilters = explanation.applied_filters || explanation.appliedFilters || {};
  const docs = explanation.documents_used || explanation.documentsUsed || [];
  const filterRows = buildAppliedFilterRows(appliedFilters);
  const explanationSummary = buildExplanationSummary(sqlSource, appliedFilters);
 
  return (
    <div className="mt-2 rounded-2xl border border-slate-200 bg-white p-3 text-xs text-slate-700 shadow-sm">
      <div className="mb-2 font-medium text-slate-800">Why this answer?</div>
      <p className="mb-3 rounded-xl bg-emerald-50 px-3 py-2 text-[13px] leading-5 text-emerald-900">
        {explanationSummary}
      </p>
 
      {sqlSource && Object.keys(sqlSource).length > 0 && (
        <div className="mb-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Backend data used</div>
          <div className="mt-1 rounded-xl bg-slate-50 px-3 py-2 text-[13px] font-medium text-slate-800">
            {humanizeDataSource(sqlSource.table)}
          </div>
        </div>
      )}
 
      <div className="mb-2">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Filters applied</div>
        {filterRows.length ? (
          <div className="mt-2 grid gap-2">
            {filterRows.map((row) => (
              <div key={row.label} className="flex items-center justify-between gap-3 rounded-xl bg-slate-50 px-3 py-2">
                <span className="text-[12px] text-slate-500">{row.label}</span>
                <span className="text-right text-[12px] font-medium text-slate-800">{row.value}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-1 text-[13px] text-slate-800">No extra filters were applied.</div>
        )}
      </div>
 
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Evidence type</div>
        {!docs.length ? (
          <div className="rounded-xl bg-slate-50 px-3 py-2 text-[13px] text-slate-700">
            Answered directly from structured database records. No document snippets were needed.
          </div>
        ) : null}
        <ul className="list-inside list-disc space-y-1">
          {docs.map((d: any, idx: number) => {
            const md = d.metadata || {};
            const facility = md.facility || md.facility_name || md.facility_id || 'Unknown facility';
            const org = md.organization || md.organization_name || md.organization_id || '';
            const period = md.reporting_period || md.reporting_period_id || '';
            const scope = md.scope || '';
            const category = md.category || md.subcategory || '';
            return (
              <li key={idx} className="text-[13px] text-slate-800">
                <div className="font-medium">{d.source || facility}</div>
                <div className="text-slate-600">{[org && `Org: ${org}`, facility && `Facility: ${facility}`, period && `Period: ${period}`, scope && `Scope: ${scope}`, category && `Category: ${category}`].filter(Boolean).join(' • ')}</div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

function CleanExplanationPanel({ explanation }: { explanation: any }) {
  if (!explanation) return null;

  const route = String(explanation.route || explanation.tool || '').toLowerCase();
  const summary = typeof explanation.summary === 'string' ? explanation.summary.trim() : '';
  const sqlSource = explanation.sql_source || explanation.sqlSource || {};
  const appliedFilters = explanation.applied_filters || explanation.appliedFilters || {};
  const docs = explanation.documents_used || explanation.documentsUsed || [];
  const filterLines = formatExplanationFilters(appliedFilters);
  const usesSqlOnly = !docs.length && (route === 'sql' || Object.keys(sqlSource).length > 0);

  return (
    <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-700 mt-2">
      <div className="mb-2 font-medium text-slate-800">Explanation</div>

      {summary ? (
        <div className="mb-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-[13px] text-slate-700">
          {summary}
        </div>
      ) : null}

      {sqlSource && Object.keys(sqlSource).length > 0 && (
        <div className="mb-2">
          <div className="text-[11px] font-semibold text-slate-600">Source</div>
          <div className="text-[13px] text-slate-800">{sqlSource.table || 'Structured SQL result'}</div>
          {sqlSource.line ? <div className="mt-1 text-[12px] text-slate-600">{sqlSource.line}</div> : null}
        </div>
      )}

      <div className="mb-2">
        <div className="text-[11px] font-semibold text-slate-600">Applied Filters</div>
        <div className="text-[13px] text-slate-800">
          {filterLines.length ? (
            <ul className="list-inside list-disc space-y-1">
              {filterLines.map((line: string) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : (
            'None'
          )}
        </div>
      </div>

      {docs.length ? (
        <div>
          <div className="text-[11px] font-semibold text-slate-600 mb-1">{`Documents used (${docs.length})`}</div>
          <ul className="list-inside list-disc space-y-1">
            {docs.map((d: any, idx: number) => {
              const md = d.metadata || {};
              const facility = md.facility || md.facility_name || md.facility_id || 'Unknown facility';
              const org = md.organization || md.organization_name || md.organization_id || '';
              const period = md.reporting_period || md.reporting_period_id || '';
              const scope = md.scope || '';
              const category = md.category || md.subcategory || '';
              return (
                <li key={idx} className="text-[13px] text-slate-800">
                  <div className="font-medium">{d.source || facility}</div>
                  <div className="text-slate-600">
                    {[org && `Org: ${org}`, facility && `Facility: ${facility}`, period && `Period: ${period}`, scope && `Scope: ${scope}`, category && `Category: ${category}`]
                      .filter(Boolean)
                      .join(' | ')}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function AIChatbot() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      type: 'bot',
      content:
        "Hello! I'm your AI sustainability assistant.\nI can help you analyze emissions, explain terms, answer follow-up questions, and explore your CarbonView data. How can I assist you today?",
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [chatScope, setChatScope] = useState<DashboardFilters>({});
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([
    'Show my latest monthly emissions.',
    'Compare this month with the previous month.',
    'What is carbon emission?',
    'Which scope contributes the most?',
  ]);
  const scrollRef = useRef<HTMLDivElement | null>(null);
 
  useEffect(() => {
    const loadSuggestions = async () => {
      try {
        const response = await fetch(apiEndpoints.ragSuggestions);
        if (!response.ok) {
          return;
        }
        const data: SuggestionsResponse = await response.json();
        if (data.questions?.length) {
          setSuggestedQuestions(data.questions.slice(0, 4));
        }
      } catch (error) {
        return;
      }
    };
 
    void loadSuggestions();
  }, []);
 
  useEffect(() => {
    const loadChatScope = async () => {
      try {
        const summary = await fetchDashboardSummary();
        setChatScope({
          organization_id: summary.filters.organization_id ?? summary.entity.organization?.id ?? null,
          facility_id: summary.filters.facility_id ?? summary.entity.facility?.id ?? null,
          reporting_period_id: summary.filters.reporting_period_id ?? summary.entity.reporting_period?.id ?? null,
        });
      } catch (error) {
        return;
      }
    };
 
    void loadChatScope();
  }, []);
 
  useEffect(() => {
    if (!scrollRef.current) {
      return;
    }
 
    scrollRef.current.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, isLoading]);
 
  const starterChips = useMemo(
    () => [
      { icon: BarChart2, label: suggestedQuestions[0] || 'Show my latest monthly emissions.' },
      { icon: Sparkles, label: suggestedQuestions[1] || 'Compare this month with the previous month.' },
      { icon: Lightbulb, label: suggestedQuestions[2] || 'What is carbon emission?' },
      { icon: MessageCircle, label: suggestedQuestions[3] || 'Which scope contributes the most?' },
    ],
    [suggestedQuestions],
  );
 
  const appendBotMessage = (content: string, tone: Message['tone'] = 'default') => {
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-bot`,
        type: 'bot',
        content,
        tone,
      },
    ]);
  };
 
  const handleSuggestedQuestion = (question: string) => {
    setInput(question);
    void handleSend(question);
  };
 
  const toggleExplanation = (id: string) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, explanationOpen: !m.explanationOpen } : m)));
  };
 
  const handleSend = async (overrideInput?: string) => {
    const messageToSend = normalizeInput(overrideInput ?? input);
    if (!messageToSend || isLoading) return;
 
    const updatedMessages = [
      ...messages,
      {
        id: `${Date.now()}-user`,
        type: 'user' as const,
        content: messageToSend,
      },
    ];
    setMessages(updatedMessages);
    setInput('');
 
    if (isGreeting(messageToSend)) {
      appendBotMessage(getGreetingResponse(messageToSend));
      return;
    }
 
    setIsLoading(true);
 
    try {
      const history = messages
        .filter((message) => message.id !== '1')
        .slice(-10)
        .map((message) => ({
          role: message.type === 'user' ? 'user' : 'assistant',
          content: message.content,
        }));
 
      const response = await fetch(apiEndpoints.ragAsk, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: messageToSend,
          history,
          organization_id: chatScope.organization_id,
          facility_id: chatScope.facility_id,
          reporting_period_id: chatScope.reporting_period_id,
        }),
      });
 
      const data: RagResponse = await response.json();
      const answer = data.answer || data.error || '';
      const chart = data.tool_output?.chart;
      const explanation = (data as any).explanation || null;
 
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-bot`,
          type: 'bot',
          content: formatRagAnswer(answer || 'I could not generate a response right now.'),
          tone: shouldShowInsight(messageToSend) ? 'insight' : 'default',
          chart,
          explanation,
          explanationOpen: false,
        },
      ]);
    } catch (error) {
      appendBotMessage(
        'I could not reach the assistant service right now. Please check that the backend is running and try again.',
      );
    } finally {
      setIsLoading(false);
    }
  };
 
  return (
    <>
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="fixed bottom-6 right-6 z-[1100] flex h-[72px] w-[72px] items-center justify-center rounded-full bg-teal-500 text-white shadow-[0_18px_45px_rgba(20,184,166,0.35)] transition-all hover:-translate-y-1 hover:bg-teal-600 hover:shadow-[0_24px_55px_rgba(20,184,166,0.42)]"
          aria-label="Open AI Assistant"
        >
          <MessageCircle className="h-8 w-8" />
        </button>
      )}
 
      {isOpen && (
        <div className="fixed bottom-6 right-6 z-[1100] flex h-[min(720px,calc(100vh-3rem))] w-[460px] max-w-[calc(100vw-1rem)] flex-col overflow-hidden rounded-[22px] border border-slate-200 bg-white shadow-[0_30px_80px_rgba(15,23,42,0.2)]">
          <div className="bg-[linear-gradient(135deg,#0fb9a8_0%,#10b981_100%)] px-5 py-5 text-white">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="rounded-2xl bg-white/14 p-3 backdrop-blur">
                  <MessageCircle className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-[15px] font-semibold">AI Sustainability Assistant</h3>
                  <p className="mt-0.5 text-sm text-emerald-50">Online</p>
                </div>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="rounded-xl p-2 text-white/90 transition-colors hover:bg-white/10 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>
 
          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto bg-white px-5 py-5">
            {messages.map((message) => (
              <div key={message.id} className={`flex ${message.type === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`flex max-w-[88%] gap-3 ${message.type === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                  <div
                    className={`rounded-3xl px-4 py-3 text-sm leading-6 shadow-sm ${
                      message.type === 'user'
                        ? 'bg-teal-500 text-white'
                        : message.tone === 'clarify'
                          ? 'bg-slate-100 text-slate-800'
                          : message.tone === 'insight'
                            ? 'bg-slate-100 text-slate-800'
                            : 'bg-slate-100 text-slate-800'
                    }`}
                  >
                    <p className="whitespace-pre-line">{message.content}</p>
                    {message.type === 'bot' && message.chart ? <ChatChart chart={message.chart} /> : null}
 
                    {message.type === 'bot' && message.explanation ? (
                      <div className="mt-3 flex flex-col gap-2">
                        <button
                          onClick={() => toggleExplanation(message.id)}
                          className="text-xs font-medium text-emerald-600 hover:underline"
                        >
                          Why this answer
                        </button>

                        {message.explanationOpen && <CleanExplanationPanel explanation={message.explanation} />}
                      </div>
                    ) : null}
 
                    {message.tone === 'insight' && message.type === 'bot' && (
                      <div className="mt-3 rounded-2xl bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500">
                        Insight-ready summary
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
 
            {isLoading && (
              <div className="flex justify-start">
                <div className="flex max-w-[80%] gap-3">
                  <div className="rounded-3xl bg-slate-100 px-4 py-3 shadow-sm">
                    <div className="flex items-center gap-1.5">
                      <span className="h-2 w-2 animate-pulse rounded-full bg-slate-400 [animation-delay:-0.2s]" />
                      <span className="h-2 w-2 animate-pulse rounded-full bg-slate-400 [animation-delay:-0.1s]" />
                      <span className="h-2 w-2 animate-pulse rounded-full bg-slate-400" />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
 
          {messages.length === 1 && (
            <div className="bg-white px-5 pb-4">
              <p className="mb-3 text-sm font-medium text-slate-500">Suggested questions:</p>
              <div className="grid gap-2">
                {starterChips.map(({ icon: Icon, label }) => (
                  <button
                    key={label}
                    onClick={() => handleSuggestedQuestion(label)}
                    className="flex items-center gap-3 rounded-2xl bg-slate-50 px-3 py-3 text-left text-sm font-medium text-slate-700 transition-all hover:bg-slate-100"
                  >
                    <div className="rounded-xl bg-white p-2 text-teal-500 shadow-sm">
                      <Icon className="h-4 w-4" />
                    </div>
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
 
          <div className="border-t border-slate-100 bg-white px-5 py-4">
            <div className="flex items-center gap-3">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    void handleSend();
                  }
                }}
                placeholder="Ask me anything..."
                rows={1}
                className="max-h-28 min-h-[52px] flex-1 resize-none rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none placeholder:text-slate-400"
              />
              <button
                onClick={() => void handleSend()}
                disabled={!normalizeInput(input) || isLoading}
                className="rounded-2xl bg-emerald-300 p-3 text-white transition-all hover:bg-emerald-400 active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
 
 