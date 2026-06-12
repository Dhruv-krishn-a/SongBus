import { useEffect, useState, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  Wand2, X, Check, Search, Filter, ChevronLeft, ChevronRight, 
  Music2, Clock, Trash2, ArrowUp, ArrowDown, 
  AlertCircle, Info, CheckCircle2, RefreshCw, Loader2, Brain
} from 'lucide-react';

const PAGE_SIZE = 12;

type Track = {
  id: number;
  title: string;
  artist: string;
  album?: string | null;
  duration_ms?: number | null;
  thumbnail_url?: string | null;
  genre?: string | null;
  mood?: string | null;
  source?: string | null;
  created_at?: string | null;
};

type YouTubePlaylist = {
  id: string;
  title: string;
  description?: string;
  track_count: number;
  source?: string;
};

type NormalizePreview = {
  id: number;
  current_title: string;
  current_artist: string;
  proposed_title: string;
  proposed_artist: string;
};

type ModalConfig = {
  show: boolean;
  type: 'info' | 'success' | 'error' | 'confirm';
  title: string;
  message: string;
  onConfirm?: () => void;
  confirmText?: string;
};

const formatDuration = (ms: number | null | undefined) => {
  if (!ms) return '--:--';
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
};

const formatDate = (dateStr: string | null | undefined) => {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleDateString(undefined, { 
    month: 'short', 
    day: 'numeric',
    year: 'numeric'
  });
};

const Library = () => {
  const { token } = useAuth();
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [status, setStatus] = useState({ youtube_connected: false });
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  
  // Filtering & Sorting states
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [artistFilter, setArtistFilter] = useState('');
  const [genreFilter, setGenreFilter] = useState('');
  const [moodFilter, setMoodFilter] = useState('');
  const [sortBy, setSortBy] = useState('created_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [showMobileFilters, setShowMobileFilters] = useState(false);

  // Bulk Normalize states
  const [showBatchModal, setShowBatchModal] = useState(false);
  const [previewData, setPreviewData] = useState<NormalizePreview[]>([]);
  const [selectedForBatch, setSelectedForBatch] = useState<Set<number>>(new Set());
  const [isBatchProcessing, setIsBatchProcessing] = useState(false);
  const [isClassifyingAi, setIsClassifyingAi] = useState(false);

  // Global Feedback Modal
  const [modal, setModal] = useState<ModalConfig>({
    show: false,
    type: 'info',
    title: '',
    message: ''
  });

  // Persistent Playlists state
  const [youtubePlaylists, setYouTubePlaylists] = useState<YouTubePlaylist[]>(() => {
    const saved = localStorage.getItem('yt_playlists');
    return saved ? JSON.parse(saved) : [];
  });
  const [playlistsLoading, setPlaylistsLoading] = useState(false);
  const [selectedPlaylistId, setSelectedPlaylistId] = useState(() => {
    return localStorage.getItem('yt_selected_id') || '';
  });

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
    }, 500);
    return () => clearTimeout(timer);
  }, [search]);

  const fetchStatus = useCallback(() => {
    if (!token) return;
    fetch('/api/integrations/status', {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(res => res.json())
      .then(data => setStatus(data))
      .catch(console.error);
  }, [token]);

  const fetchYouTubePlaylists = useCallback(() => {
    if (!token || !status.youtube_connected) return;

    setPlaylistsLoading(true);
    fetch('/api/integrations/youtube/playlists', {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(async res => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to load YouTube playlists');
        return data;
      })
      .then(data => {
        const playlists = data.playlists || [];
        setYouTubePlaylists(playlists);
        localStorage.setItem('yt_playlists', JSON.stringify(playlists));
        if (playlists.length > 0) {
          const firstId = playlists[0].id;
          setSelectedPlaylistId(firstId);
          localStorage.setItem('yt_selected_id', firstId);
        }
      })
      .catch(err => {
        setModal({
          show: true,
          type: 'error',
          title: 'Connection Failed',
          message: `We couldn't reach YouTube Music: ${err.message}.`
        });
      })
      .finally(() => setPlaylistsLoading(false));
  }, [token, status.youtube_connected]);

  const handlePlaylistChange = (id: string) => {
    setSelectedPlaylistId(id);
    localStorage.setItem('yt_selected_id', id);
  };

  const fetchTracks = useCallback((targetPage = page) => {
    if (!token) return;

    const timeoutId = setTimeout(() => setLoading(true), 0);
    let url = `/api/music/library?page=${targetPage}&page_size=${PAGE_SIZE}&sort_by=${sortBy}&sort_order=${sortOrder}`;
    if (debouncedSearch) url += `&search=${encodeURIComponent(debouncedSearch)}`;
    if (artistFilter) url += `&artist=${encodeURIComponent(artistFilter)}`;
    if (genreFilter) url += `&genre=${encodeURIComponent(genreFilter)}`;
    if (moodFilter) url += `&mood=${encodeURIComponent(moodFilter)}`;

    fetch(url, {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(res => res.json())
      .then(data => {
        setTracks(data.tracks || []);
        setPage(data.page || targetPage);
        setTotal(data.total || 0);
        setTotalPages(data.total_pages || 0);
      })
      .catch(console.error)
      .finally(() => {
        clearTimeout(timeoutId);
        setLoading(false);
      });
  }, [token, page, debouncedSearch, artistFilter, genreFilter, moodFilter, sortBy, sortOrder]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    fetchTracks(1);
  }, [token, debouncedSearch, artistFilter, genreFilter, moodFilter, sortBy, sortOrder]);

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
    fetchTracks(newPage);
  };

  const pollTask = useCallback(async (taskId: string) => {
    const poll = async () => {
      try {
        const res = await fetch(`/api/tasks/${taskId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (!res.ok) {
           setImporting(false);
           return;
        }
        const task = await res.json();

        if (task.status === 'completed') {
          setModal({
            show: true,
            type: 'success',
            title: 'Import Successful',
            message: `${task.result.message}. Linked ${task.result.linked_tracks} tracks and added ${task.result.imported_tracks} new songs.`
          });
          setImporting(false);
          handlePageChange(1);
          return;
        }

        if (task.status === 'failed') {
          setModal({
            show: true,
            type: 'error',
            title: 'Import Failed',
            message: task.error || 'Something went wrong during the background process.'
          });
          setImporting(false);
          return;
        }

        // Show live progress for running/pending tasks
        setModal({
          show: true,
          type: 'info',
          title: 'Import in Progress',
          message: task.message + (task.total ? ` (${task.progress} / ${task.total})` : '')
        });

        // Continue polling
        setTimeout(poll, 1500);
      } catch (err) {
        console.error('Polling error:', err);
        setImporting(false);
      }
    };
    poll();
  }, [token, handlePageChange]);

  const handleImport = async () => {
    if (!token || !selectedPlaylistId) return;

    setImporting(true);
    setModal({
      show: true,
      type: 'info',
      title: 'Import Started',
      message: 'Your playlist is being processed in the background. Please wait...'
    });

    try {
      const res = await fetch(`/api/integrations/youtube/import-playlist/${selectedPlaylistId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });

      const data = await res.json();
      if (res.ok && data.task_id) {
        pollTask(data.task_id);
      } else {
        setImporting(false);
        setModal({
          show: true,
          type: 'error',
          title: 'Import Failed',
          message: data.detail || 'Failed to start background import.'
        });
      }
    } catch (err) {
      console.error(err);
      setImporting(false);
    }
  };

  const handleNormalize = async (trackId: number) => {
    if (!token) return;

    try {
      const res = await fetch(`/api/music/normalize/${trackId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });

      if (res.ok) {
        const updatedTrack = await res.json();
        setTracks(prev => prev.map(t => t.id === trackId ? updatedTrack : t));
      }
    } catch (err) {
      console.error(err);
    }
  };

  const confirmDelete = (trackId: number, title: string) => {
    setModal({
      show: true,
      type: 'confirm',
      title: 'Remove Track',
      message: `Are you sure you want to remove "${title}" from your library?`,
      confirmText: 'Remove Song',
      onConfirm: () => handleDelete(trackId)
    });
  };

  const handleDelete = async (trackId: number) => {
    if (!token) return;

    try {
      const res = await fetch(`/api/music/tracks/${trackId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` }
      });

      if (res.ok) {
        setTracks(prev => prev.filter(t => t.id !== trackId));
        setTotal(prev => prev - 1);
        setModal({ show: false, type: 'info', title: '', message: '' });
      }
    } catch (err) {
      console.error(err);
    }
  };

  const toggleSort = (field: string) => {
    if (sortBy === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(field);
      setSortOrder('asc');
    }
  };

  const startBatchNormalize = async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch('/api/music/normalize/preview', {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      setPreviewData(data.preview || []);
      setSelectedForBatch(new Set((data.preview || []).map((p: NormalizePreview) => p.id)));
      setShowBatchModal(true);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleBatchCommit = async () => {
    if (!token || selectedForBatch.size === 0) return;
    setIsBatchProcessing(true);
    try {
      const res = await fetch('/api/music/normalize/batch', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}` 
        },
        body: JSON.stringify({ track_ids: Array.from(selectedForBatch) })
      });
      if (res.ok) {
        setShowBatchModal(false);
        setModal({
          show: true,
          type: 'success',
          title: 'Batch Complete',
          message: `Successfully normalized ${selectedForBatch.size} tracks.`
        });
        handlePageChange(1);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsBatchProcessing(false);
    }
  };

  const toggleBatchTrack = (id: number) => {
    const next = new Set(selectedForBatch);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedForBatch(next);
  };

  const handleClassifyAi = async () => {
    if (!token) return;
    setIsClassifyingAi(true);
    setModal({
      show: true,
      type: 'info',
      title: 'AI Classification Started',
      message: 'Gemini is analyzing your library. This may take a minute...'
    });

    try {
      const res = await fetch('/api/music/classify-all', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      
      if (res.ok) {
        setModal({
          show: true,
          type: 'success',
          title: 'Classification Complete',
          message: data.message
        });
        handlePageChange(1); // Refresh tracks to show new genres/moods
      } else {
        setModal({
          show: true,
          type: 'error',
          title: 'Classification Failed',
          message: data.detail || 'An error occurred during AI analysis.'
        });
      }
    } catch (err: unknown) {
      console.error(err);
      setModal({
        show: true,
        type: 'error',
        title: 'Classification Failed',
        message: err instanceof Error ? err.message : 'Unknown error'
      });
    } finally {
      setIsClassifyingAi(false);
    }
  };

  const clearFilters = () => {
    setSearch('');
    setArtistFilter('');
    setGenreFilter('');
    setMoodFilter('');
  };

  const renderSortIndicator = (field: string) => {
    if (sortBy !== field) return null;
    return sortOrder === 'asc' ? <ArrowUp className="w-3 h-3 ml-1 text-primary" /> : <ArrowDown className="w-3 h-3 ml-1 text-primary" />;
  };

  return (
    <div className="max-w-7xl mx-auto px-1 sm:px-2 md:px-0 space-y-6 md:space-y-8 animate-in fade-in duration-500 pb-20">
      {/* Page Header */}
      <header className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 md:gap-6">
        <div className="text-center lg:text-left">
          <h1 className="text-2xl md:text-3xl font-black text-gray-900 tracking-tight">Music Library</h1>
          <p className="text-sm md:text-base text-gray-500 font-medium">Explore and manage your {total} tracks.</p>
        </div>
        
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
          <button
            onClick={startBatchNormalize}
            className="flex-1 sm:flex-none flex items-center justify-center gap-2 bg-white text-gray-900 px-5 py-3 rounded-2xl border border-gray-200 shadow-sm hover:shadow-md hover:border-primary/30 transition-all font-bold text-sm group"
          >
            <Wand2 className="w-4 h-4 text-primary" />
            Normalize All
          </button>
          
          <button
            onClick={handleClassifyAi}
            disabled={isClassifyingAi}
            className="flex-1 sm:flex-none flex items-center justify-center gap-2 bg-gray-900 text-white px-5 py-3 rounded-2xl shadow-xl shadow-gray-900/10 hover:bg-gray-800 transition-all font-bold text-sm group disabled:opacity-50"
          >
            {isClassifyingAi ? <Loader2 className="w-4 h-4 animate-spin" /> : <Brain className="w-4 h-4 text-primary" />}
            {isClassifyingAi ? 'Classifying...' : 'Classify using AI'}
          </button>

          {status.youtube_connected && (
            <div className="flex-1 sm:flex-none flex items-stretch gap-2 bg-white p-1.5 rounded-2xl border border-gray-200 shadow-sm max-w-full sm:max-w-md lg:max-w-lg">
              {youtubePlaylists.length === 0 ? (
                <button
                  onClick={fetchYouTubePlaylists}
                  disabled={playlistsLoading}
                  className="flex-1 flex items-center justify-center gap-2 py-2 px-4 text-sm font-black text-gray-400 hover:text-primary transition-colors disabled:opacity-50 whitespace-nowrap"
                >
                  {playlistsLoading ? (
                    <Loader2 className="w-4 h-4 animate-spin text-primary" />
                  ) : (
                    <RefreshCw className="w-4 h-4" />
                  )}
                  {playlistsLoading ? 'Scanning...' : 'Fetch Playlists'}
                </button>
              ) : (
                <div className="flex items-center gap-1 w-full min-w-0">
                  <div className="flex-1 flex items-center px-2 min-w-0 bg-gray-50 rounded-xl h-10">
                    <Music2 className="w-4 h-4 text-primary mr-2 flex-shrink-0" />
                    <select
                      value={selectedPlaylistId}
                      onChange={(e) => handlePlaylistChange(e.target.value)}
                      disabled={importing}
                      className="bg-transparent text-[13px] font-bold focus:outline-none w-full truncate cursor-pointer appearance-none"
                    >
                      {youtubePlaylists.map((p) => (
                        <option key={p.id} value={p.id}>{p.title} ({p.track_count})</option>
                      ))}
                    </select>
                  </div>
                  <button
                    onClick={handleImport}
                    disabled={importing || !selectedPlaylistId}
                    className="bg-gray-900 text-white px-5 h-10 rounded-xl text-[11px] font-black uppercase tracking-wider hover:bg-gray-800 transition disabled:opacity-50 whitespace-nowrap"
                  >
                    {importing ? '...' : 'Import'}
                  </button>
                  <button
                    onClick={fetchYouTubePlaylists}
                    disabled={playlistsLoading || importing}
                    className="p-2.5 text-gray-400 hover:text-primary transition-colors rounded-xl bg-gray-50"
                    title="Refresh List"
                  >
                    <RefreshCw className={`w-4 h-4 ${playlistsLoading ? 'animate-spin text-primary' : ''}`} />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </header>

      {/* Control Bar */}
      <div className="sticky top-[72px] lg:top-4 z-20 bg-white/90 backdrop-blur-xl border border-gray-100 rounded-2xl md:rounded-3xl shadow-lg shadow-gray-200/20 p-2 mx-1 sm:mx-0">
        <div className="flex flex-col md:flex-row items-stretch md:items-center gap-2">
          <div className="flex-1 relative group">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 group-focus-within:text-primary transition-colors" />
            <input
              type="text"
              placeholder="Search library..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-gray-50/50 border-none rounded-xl md:rounded-2xl pl-11 pr-4 py-3 text-sm font-medium focus:ring-2 focus:ring-primary/10 outline-none transition-all"
            />
          </div>
          
          <button 
            onClick={() => setShowMobileFilters(!showMobileFilters)}
            className="md:hidden flex items-center justify-center gap-2 px-4 py-3 bg-gray-50 rounded-xl text-sm font-bold text-gray-600"
          >
            <Filter className="w-4 h-4" />
            Filters { (artistFilter || genreFilter || moodFilter) && '•' }
          </button>

          <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col md:flex-row items-stretch gap-2`}>
            <input
              type="text"
              placeholder="Artist..."
              value={artistFilter}
              onChange={(e) => setArtistFilter(e.target.value)}
              className="md:w-36 bg-gray-50/50 border-none rounded-xl md:rounded-2xl px-4 py-3 text-sm font-medium focus:ring-2 focus:ring-primary/10 outline-none"
            />
            <select
              value={genreFilter}
              onChange={(e) => setGenreFilter(e.target.value)}
              className="md:w-36 bg-gray-50/50 border-none rounded-xl md:rounded-2xl px-4 py-3 text-sm font-medium focus:ring-2 focus:ring-primary/10 outline-none appearance-none"
            >
              <option value="">All Genres</option>
              <option value="Bollywood">Bollywood</option>
              <option value="Electronic/Remix">Electronic</option>
              <option value="Rock/Metal">Rock</option>
              <option value="Pop">Pop</option>
              <option value="Hip-Hop/Rap">Hip-Hop</option>
            </select>
            {(search || artistFilter || genreFilter || moodFilter) && (
              <button onClick={clearFilters} className="px-4 py-2 text-sm font-bold text-red-500 hover:bg-red-50 rounded-xl transition-colors">
                Clear
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Responsive View Container */}
      <div className="w-full">
        {/* Desktop Table View (lg+) */}
        <div className="hidden lg:block bg-white rounded-[32px] border border-gray-100 shadow-xl shadow-gray-200/40 overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-gray-50 bg-gray-50/30 text-[10px] md:text-[11px] font-black text-gray-400 uppercase tracking-widest">
                <th onClick={() => toggleSort('title')} className="pl-8 pr-4 py-5 cursor-pointer hover:text-primary transition-colors select-none">
                  <div className="flex items-center">Track {renderSortIndicator('title')}</div>
                </th>
                <th onClick={() => toggleSort('album')} className="px-4 py-5 cursor-pointer hover:text-primary transition-colors select-none">
                  <div className="flex items-center">Album {renderSortIndicator('album')}</div>
                </th>
                <th onClick={() => toggleSort('genre')} className="px-4 py-5 cursor-pointer hover:text-primary transition-colors select-none">
                  <div className="flex items-center">Classification {renderSortIndicator('genre')}</div>
                </th>
                <th className="px-4 py-5 text-center"><Clock className="w-3.5 h-3.5 mx-auto" /></th>
                <th onClick={() => toggleSort('created_at')} className="pl-4 pr-8 py-5 cursor-pointer hover:text-primary transition-colors select-none text-right">
                  <div className="flex items-center justify-end">Added {renderSortIndicator('created_at')}</div>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading ? (
                [...Array(6)].map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    <td colSpan={5} className="px-8 py-6">
                      <div className="flex gap-4"><div className="w-12 h-12 bg-gray-100 rounded-xl" /><div className="flex-1 space-y-2"><div className="h-4 bg-gray-100 rounded w-1/4" /><div className="h-3 bg-gray-50 rounded w-1/6" /></div></div>
                    </td>
                  </tr>
                ))
              ) : tracks.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-8 py-20 text-center text-gray-400">
                    <Music2 className="w-12 h-12 mx-auto mb-4 opacity-20" />
                    <p className="font-bold text-gray-500">No tracks found in your library.</p>
                  </td>
                </tr>
              ) : tracks.map((track) => (
                <tr key={track.id} className="group hover:bg-primary/[0.02] transition-all">
                  <td className="pl-8 pr-4 py-4">
                    <div className="flex items-center gap-4">
                      <div className="relative w-12 h-12 md:w-14 md:h-14 rounded-2xl overflow-hidden bg-gray-100 flex-shrink-0 shadow-sm">
                        {track.thumbnail_url ? (
                          <img src={track.thumbnail_url} alt="" className="w-full h-full object-cover" />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center text-gray-300"><Music2 className="w-6 h-6" /></div>
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <p className="font-bold text-gray-900 truncate leading-tight">{track.title}</p>
                          <div className="flex items-center opacity-0 group-hover:opacity-100 transition-all">
                            <button onClick={() => handleNormalize(track.id)} className="p-1.5 text-primary bg-primary/5 hover:bg-primary hover:text-white rounded-lg transition-all mr-1"><Wand2 className="w-3 h-3.5" /></button>
                            <button onClick={() => confirmDelete(track.id, track.title)} className="p-1.5 text-red-500 bg-red-50 hover:bg-red-500 hover:text-white rounded-lg transition-all"><Trash2 className="w-3 h-3.5" /></button>
                          </div>
                        </div>
                        <button onClick={() => setArtistFilter(track.artist)} className="text-xs md:text-sm font-bold text-gray-400 hover:text-primary transition-colors truncate block">{track.artist}</button>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-4 text-sm font-semibold text-gray-500 italic max-w-[160px] truncate">{track.album || '—'}</td>
                  <td className="px-4 py-4">
                    <div className="flex gap-2">
                      <span className="px-2 py-0.5 rounded-lg bg-blue-50 text-blue-600 text-[10px] font-black uppercase tracking-wider">{track.genre || 'VARIOUS'}</span>
                      <span className={`px-2 py-0.5 rounded-lg text-[10px] font-black uppercase tracking-wider ${track.mood === 'Energetic/Party' ? 'bg-orange-50 text-orange-600' : 'bg-green-50 text-green-600'}`}>{track.mood || 'NEUTRAL'}</span>
                    </div>
                  </td>
                  <td className="px-4 py-4 text-center text-sm font-black text-gray-400 tabular-nums">{formatDuration(track.duration_ms)}</td>
                  <td className="pl-4 pr-8 py-4 text-right">
                    <span className="text-xs font-bold text-gray-400 whitespace-nowrap">{formatDate(track.created_at)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Mobile & Tablet Card View (below lg) */}
        <div className="lg:hidden grid grid-cols-1 md:grid-cols-2 gap-4">
          {loading ? (
            [...Array(4)].map((_, i) => (
              <div key={i} className="bg-white p-5 rounded-[24px] shadow-sm animate-pulse flex gap-4">
                <div className="w-20 h-20 bg-gray-100 rounded-2xl flex-shrink-0" />
                <div className="flex-1 space-y-3"><div className="h-4 bg-gray-100 rounded w-3/4" /><div className="h-3 bg-gray-50 rounded w-1/2" /></div>
              </div>
            ))
          ) : tracks.map((track) => (
            <div key={track.id} className="bg-white p-4 md:p-5 rounded-[24px] shadow-sm border border-gray-100 flex flex-col sm:flex-row gap-4 active:scale-[0.98] transition-transform">
              <div className="w-full sm:w-24 h-40 sm:h-24 rounded-2xl overflow-hidden bg-gray-100 flex-shrink-0 relative">
                <img src={track.thumbnail_url || ''} alt="" className="w-full h-full object-cover" />
                <div className="absolute top-2 right-2 flex flex-col gap-2">
                  <button onClick={() => handleNormalize(track.id)} className="p-2 bg-white/90 backdrop-blur-md text-primary rounded-xl shadow-sm active:scale-90 transition-transform"><Wand2 className="w-5 h-5" /></button>
                  <button onClick={() => confirmDelete(track.id, track.title)} className="p-2 bg-white/90 backdrop-blur-md text-red-500 rounded-xl shadow-sm active:scale-90 transition-transform"><Trash2 className="w-5 h-5" /></button>
                </div>
              </div>
              <div className="flex-1 min-w-0 flex flex-col justify-center">
                <h4 className="font-bold text-gray-900 truncate text-lg sm:text-base">{track.title}</h4>
                <p className="text-sm font-bold text-gray-400 mb-3 truncate">{track.artist}</p>
                <div className="flex items-center flex-wrap gap-2 mt-auto">
                  <span className="text-[10px] font-black uppercase tracking-widest text-primary bg-primary/5 px-2.5 py-1 rounded-lg">{track.genre || 'VARIOUS'}</span>
                  <span className="text-[10px] font-black uppercase tracking-widest text-gray-400 bg-gray-50 px-2.5 py-1 rounded-lg">{formatDuration(track.duration_ms)}</span>
                  <span className="text-[10px] font-black uppercase tracking-widest text-gray-300 ml-auto hidden sm:inline">{formatDate(track.created_at)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Pagination Controls */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 py-4 md:py-8">
        <div className="text-xs md:text-sm font-black text-gray-400 uppercase tracking-widest order-2 sm:order-1">
          {total} Items Total
        </div>
        <div className="flex items-center gap-2 order-1 sm:order-2 w-full sm:w-auto justify-center">
          <button
            onClick={() => handlePageChange(Math.max(1, page - 1))}
            disabled={loading || page <= 1}
            className="w-12 h-12 flex items-center justify-center rounded-2xl bg-white border border-gray-200 text-gray-600 disabled:opacity-20 hover:shadow-md transition-all active:scale-90"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          <div className="bg-gray-900 text-white px-6 h-12 flex items-center rounded-2xl font-black text-sm shadow-xl shadow-gray-900/10">
            {page} <span className="mx-2 opacity-30">/</span> {totalPages}
          </div>
          <button
            onClick={() => handlePageChange(Math.min(totalPages || 1, page + 1))}
            disabled={loading || page >= totalPages}
            className="w-12 h-12 flex items-center justify-center rounded-2xl bg-white border border-gray-200 text-gray-600 disabled:opacity-20 hover:shadow-md transition-all active:scale-90"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Feedback Modal System */}
      {modal.show && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-950/60 backdrop-blur-sm" onClick={() => modal.type !== 'confirm' && setModal({ ...modal, show: false })} />
          <div className="relative bg-white w-full max-w-sm sm:max-w-md rounded-[32px] shadow-2xl overflow-hidden p-6 sm:p-8 animate-in fade-in zoom-in duration-200">
             <div className="flex flex-col items-center text-center">
              <div className={`w-16 h-16 sm:w-20 sm:h-20 rounded-full flex items-center justify-center mb-4 sm:mb-6 ${
                modal.type === 'error' ? 'bg-red-50 text-red-500' :
                modal.type === 'success' ? 'bg-green-50 text-green-500' :
                modal.type === 'confirm' ? 'bg-orange-50 text-orange-500' : 'bg-blue-50 text-primary'
              }`}>
                {modal.type === 'error' && <AlertCircle className="w-8 h-8 sm:w-10 sm:h-10" />}
                {modal.type === 'success' && <CheckCircle2 className="w-8 h-8 sm:w-10 sm:h-10" />}
                {modal.type === 'confirm' && <Trash2 className="w-8 h-8 sm:w-10 sm:h-10" />}
                {modal.type === 'info' && <Info className="w-8 h-8 sm:w-10 sm:h-10" />}
              </div>
              <h3 className="text-xl sm:text-2xl font-black text-gray-900 mb-2">{modal.title}</h3>
              <p className="text-sm sm:text-base text-gray-500 font-medium leading-relaxed mb-6 sm:mb-8">{modal.message}</p>
              <div className="flex flex-col sm:flex-row items-stretch gap-3 w-full">
                {modal.type === 'confirm' ? (
                  <>
                    <button onClick={() => setModal({ ...modal, show: false })} className="order-2 sm:order-1 flex-1 px-6 h-12 sm:h-14 rounded-2xl text-sm font-black text-gray-400 hover:bg-gray-50 transition">Cancel</button>
                    <button onClick={modal.onConfirm} className="order-1 sm:order-2 flex-1 px-6 h-12 sm:h-14 rounded-2xl text-sm font-black bg-red-500 text-white shadow-lg shadow-red-500/20 hover:bg-red-600 transition">{modal.confirmText || 'Confirm'}</button>
                  </>
                ) : (
                  <button onClick={() => setModal({ ...modal, show: false })} className="w-full px-6 h-12 sm:h-14 rounded-2xl text-sm font-black bg-gray-900 text-white hover:bg-gray-800 transition">Close</button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Batch Normalize Modal */}
      {showBatchModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-2 sm:p-4">
          <div className="absolute inset-0 bg-gray-950/80 backdrop-blur-md" onClick={() => setShowBatchModal(false)} />
          <div className="relative bg-white w-full max-w-4xl h-full max-h-[90vh] sm:max-h-[85vh] rounded-3xl sm:rounded-[40px] shadow-2xl overflow-hidden flex flex-col animate-in fade-in zoom-in duration-300">
            <div className="px-6 py-5 sm:px-10 sm:py-8 border-b border-gray-50 flex items-center justify-between bg-white z-10">
              <div>
                <h2 className="text-xl sm:text-3xl font-black text-gray-900 tracking-tight">Bulk Clean-up</h2>
                <p className="text-xs sm:text-sm text-gray-500 font-medium">Review {previewData.length} suggested improvements.</p>
              </div>
              <button onClick={() => setShowBatchModal(false)} className="p-2 sm:p-3 bg-gray-50 hover:bg-gray-100 text-gray-400 rounded-full transition-all"><X className="w-5 h-5 sm:w-6 sm:h-6" /></button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 sm:p-10 space-y-4 sm:space-y-6">
              {previewData.map((item) => (
                <div key={item.id} onClick={() => toggleBatchTrack(item.id)} className={`group flex items-center gap-3 sm:gap-6 p-4 sm:p-6 rounded-2xl sm:rounded-[24px] border-2 transition-all cursor-pointer ${selectedForBatch.has(item.id) ? 'border-primary bg-primary/[0.02]' : 'border-gray-50 bg-gray-50/30 opacity-50 grayscale hover:opacity-100 hover:grayscale-0'}`}>
                  <div className={`w-8 h-8 sm:w-10 sm:h-10 rounded-lg sm:rounded-xl border-2 flex items-center justify-center transition-all flex-shrink-0 ${selectedForBatch.has(item.id) ? 'bg-primary border-primary text-white scale-110 shadow-lg shadow-primary/20' : 'bg-white border-gray-200 text-transparent'}`}><Check className="w-4 h-4 sm:w-6 sm:h-6" strokeWidth={4} /></div>
                  <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-10 min-w-0">
                    <div className="space-y-0.5 sm:space-y-1 truncate">
                      <span className="text-[8px] sm:text-[10px] font-black text-gray-400 uppercase tracking-[0.2em]">Original</span>
                      <p className="text-xs sm:text-sm font-bold text-gray-500 line-through decoration-red-400 decoration-1 sm:decoration-2 truncate">{item.current_title}</p>
                      <p className="text-[10px] sm:text-xs font-medium text-gray-400 truncate">{item.current_artist}</p>
                    </div>
                    <div className="space-y-0.5 sm:space-y-1 truncate border-t md:border-t-0 pt-2 md:pt-0">
                      <span className="text-[8px] sm:text-[10px] font-black text-primary uppercase tracking-[0.2em]">Magic Fix</span>
                      <p className="text-xs sm:text-sm font-black text-gray-900 truncate">{item.proposed_title}</p>
                      <p className="text-[10px] sm:text-xs font-bold text-primary truncate">{item.proposed_artist}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="px-6 py-5 sm:px-10 sm:py-8 bg-gray-50/50 flex flex-col md:flex-row items-center justify-between gap-4">
              <div className="text-xs sm:text-sm font-black text-gray-400 uppercase tracking-widest">{selectedForBatch.size} Selected</div>
              <div className="flex items-center gap-3 w-full md:w-auto">
                <button onClick={() => setShowBatchModal(false)} className="flex-1 md:flex-none px-6 h-12 sm:h-14 text-sm font-black text-gray-500 hover:text-gray-900 transition">Cancel</button>
                <button onClick={handleBatchCommit} disabled={isBatchProcessing || selectedForBatch.size === 0} className="flex-1 md:flex-none bg-primary text-white px-8 sm:px-12 h-12 sm:h-14 rounded-xl sm:rounded-[20px] font-black shadow-xl shadow-primary/20 hover:bg-blue-600 transition-all disabled:opacity-50 text-sm sm:text-base whitespace-nowrap">{isBatchProcessing ? 'Normalizing...' : 'Apply Changes'}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Library;
