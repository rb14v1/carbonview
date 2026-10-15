import { useEffect, useMemo, useState } from 'react';
import { BadgeCheck, Calendar, Eye, ImageOff } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../ui/select';
import { apiEndpoints, toAbsoluteBackendUrl } from '../../api';

type AccreditationItem = {
  id: number;
  name: string;
  description: string;
  file?: string;
  file_url?: string;
  created_at?: string;
};

type AccreditationResponse = {
  results?: AccreditationItem[];
};

type SortOrder = 'recent' | 'oldest';

function resolveImageUrl(item: AccreditationItem) {
  const directUrl = item.file_url || item.file || '';
  return toAbsoluteBackendUrl(directUrl);
}

export function AccreditationView() {
  const [accreditations, setAccreditations] = useState<AccreditationItem[]>([]);
  const [selectedAccreditation, setSelectedAccreditation] = useState<AccreditationItem | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [sortOrder, setSortOrder] = useState<SortOrder>('recent');

  useEffect(() => {
    fetch(apiEndpoints.certificates)
      .then((res) => {
        if (!res.ok) {
          throw new Error('Failed to load accreditation records');
        }

        return res.json();
      })
      .then((res: AccreditationResponse | AccreditationItem[]) => {
        const results = Array.isArray(res) ? res : res.results || [];
        setAccreditations(results);
        setError('');
      })
      .catch((err) => {
        console.error('ACCREDITATION API ERROR:', err);
        setAccreditations([]);
        setError('Unable to load accreditations right now.');
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  const selectedImageUrl = useMemo(() => {
    if (!selectedAccreditation) return '';
    return resolveImageUrl(selectedAccreditation);
  }, [selectedAccreditation]);

  const sortedAccreditations = useMemo(() => {
    return [...accreditations].sort((a, b) => {
      const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
      const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;

      if (sortOrder === 'recent') {
        return bTime - aTime;
      }

      return aTime - bTime;
    });
  }, [accreditations, sortOrder]);

  return (
    <div>
      <div className="mb-6 overflow-hidden rounded-[28px] border border-teal-100 bg-[linear-gradient(135deg,#ecfffb_0%,#f9fffe_52%,#dffbf7_100%)] shadow-sm">
        <div className="flex flex-col gap-6 px-6 py-8 md:flex-row md:items-center md:justify-between md:px-8">
          <div className="max-w-2xl">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-teal-600 px-3 py-1 text-xs font-medium text-white">
              <BadgeCheck className="w-3.5 h-3.5" />
              Company Recognition
            </div>
            <h1 className="mb-3 text-3xl font-semibold tracking-tight text-gray-900">
              Accreditations
            </h1>
            <p className="text-base leading-7 text-gray-600">
              Official company recognitions and environmental compliance images are available here in one place.
            </p>
          </div>

          <div className="min-w-[220px] rounded-3xl border border-teal-200 bg-white/85 p-5 backdrop-blur">
            <div className="mb-2 text-sm text-teal-700">Total Records</div>
            <div className="flex items-end gap-3">
              <span className="text-4xl font-semibold text-gray-900">{accreditations.length}</span>
              <span className="pb-1 text-sm text-gray-500">uploaded</span>
            </div>
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-[24px] border border-teal-100 bg-white shadow-sm">
        <div className="border-b border-teal-100 bg-gradient-to-r from-teal-50 via-white to-teal-50 px-6 py-5">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <h2 className="text-xl font-semibold text-gray-900">Recognition Gallery</h2>
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-teal-700">Sort by</span>
              <Select
                value={sortOrder}
                onValueChange={(value) => setSortOrder(value as SortOrder)}
              >
                <SelectTrigger className="w-[170px] border-teal-200 bg-white text-gray-900">
                  <SelectValue placeholder="Select order" />
                </SelectTrigger>
                <SelectContent className="border-teal-100 bg-white">
                  <SelectItem value="recent">Recent First</SelectItem>
                  <SelectItem value="oldest">Oldest First</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        {isLoading && (
          <div className="px-6 py-12 text-center text-sm text-gray-500">
            Loading accreditation records...
          </div>
        )}

        {!isLoading && error && (
          <div className="px-6 py-12 text-center text-sm text-red-600">
            {error}
          </div>
        )}

        {!isLoading && !error && accreditations.length === 0 && (
          <div className="px-6 py-12 text-center text-sm text-gray-500">
            No accreditation images have been uploaded yet.
          </div>
        )}

        {!isLoading && !error && accreditations.length > 0 && (
          <div className="p-6">
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            {sortedAccreditations.map((item) => {
              const imageUrl = resolveImageUrl(item);

              return (
                <button
                  key={item.id}
                  onClick={() => setSelectedAccreditation(item)}
                  className="group overflow-hidden rounded-[24px] border border-teal-100 bg-[linear-gradient(180deg,#f6fffd_0%,#ffffff_28%)] text-left shadow-sm transition-all hover:-translate-y-1 hover:border-teal-300 hover:shadow-lg"
                >
                  <div className="relative h-56 overflow-hidden bg-gradient-to-br from-teal-100 via-white to-teal-50">
                    <div className="absolute inset-x-0 top-0 z-10 flex items-center justify-between px-4 py-4">
                      <span className="inline-flex items-center gap-1 rounded-full bg-white/90 px-3 py-1 text-xs font-medium text-teal-700 shadow-sm">
                        <BadgeCheck className="w-3.5 h-3.5" />
                        Accreditation
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-full bg-teal-600 px-3 py-1 text-xs font-medium text-white shadow-sm">
                        <Eye className="w-3.5 h-3.5" />
                        View
                      </span>
                    </div>

                    {imageUrl ? (
                      <img
                        src={imageUrl}
                        alt={item.name}
                        className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                      />
                    ) : (
                      <div className="flex h-full flex-col items-center justify-center gap-2 text-gray-400">
                        <ImageOff className="w-8 h-8" />
                        <span className="text-sm">Preview unavailable</span>
                      </div>
                    )}
                  </div>

                  <div className="p-5">
                    <div className="mb-3 flex items-start justify-between gap-4">
                      <div>
                        <h3 className="text-lg font-semibold text-gray-900">{item.name}</h3>
                        <p className="text-sm text-gray-500 mt-1">
                          {item.description || 'No description provided'}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center justify-between gap-3 border-t border-teal-50 pt-4">
                      <div className="flex items-center gap-2 text-xs text-gray-500">
                        <Calendar className="w-4 h-4 text-teal-600" />
                        <span>
                          {item.created_at
                            ? new Date(item.created_at).toLocaleDateString('en-US', {
                                year: 'numeric',
                                month: 'short',
                                day: 'numeric',
                              })
                            : 'Upload date unavailable'}
                        </span>
                      </div>

                      <span className="text-xs font-medium text-teal-700">
                        Open preview
                      </span>
                    </div>
                  </div>
                </button>
              );
            })}
            </div>
          </div>
        )}
      </div>

      <Dialog
        open={Boolean(selectedAccreditation)}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedAccreditation(null);
          }
        }}
      >
        <DialogContent className="max-w-5xl overflow-hidden border-teal-100 p-0">
          {selectedAccreditation && (
            <div className="bg-white">
              <DialogHeader className="bg-gradient-to-r from-teal-50 via-white to-teal-50 px-6 pt-6 pb-4">
                <DialogTitle>{selectedAccreditation.name}</DialogTitle>
                <DialogDescription>
                  {selectedAccreditation.description || 'Accreditation image preview'}
                </DialogDescription>
              </DialogHeader>

              <div className="px-6 pb-6">
                <div className="rounded-xl border border-gray-200 bg-gray-50 overflow-hidden flex items-center justify-center min-h-[320px] max-h-[75vh]">
                  {selectedImageUrl ? (
                    <img
                      src={selectedImageUrl}
                      alt={selectedAccreditation.name}
                      className="max-h-[72vh] w-auto max-w-full object-contain"
                    />
                  ) : (
                    <div className="flex flex-col items-center gap-3 text-gray-400 py-16">
                      <ImageOff className="w-10 h-10" />
                      <span>No image available for preview.</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
