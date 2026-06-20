import { useEffect, useState, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  Wand2, X, Check, Search, ChevronLeft, ChevronRight, 
  Music2, Clock, Trash2, ArrowUp, ArrowDown, 
  AlertCircle, Info, CheckCircle2, RefreshCw, Loader2, Brain,
  Activity, Zap, Mic, Globe, Sparkles
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
  themes?: string | null;
  emotions?: string | null;
  contexts?: string | null;
  source?: string | null;
  created_at?: string | null;
  // Deep Data
  bpm?: number | null;
  energy?: number | null;
  danceability?: number | null;
  valence?: number | null;
  lyrics?: string | null;
  spotify_uri?: string | null;
  last_enriched_at?: string | null;
};

type YouTubePlaylist = {
  id: string;
  title: string;
  description?: string;
  track_count: number | string;
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
  const [activeTab, setActiveTab] = useState<'all' | 'youtube' | 'spotify'>('all');
  
  const [status, setStatus] = useState({ spotify_connected: false, youtube_connected: false });
  const [importing, setImporting] = useState(false);
  const [isCleaning, setIsCleaning] = useState(false);
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

  // Bulk Normalize states
  const [showBatchModal, setShowBatchModal] = useState(false);
  const [previewData, setPreviewData] = useState<NormalizePreview[]>([]);
  const [selectedForBatch, setSelectedForBatch] = useState<Set<number>>(new Set());
  const [isBatchProcessing, setIsBatchProcessing] = useState(false);
  const [isClassifyingAi, setIsClassifyingAi] = useState(false);

  // Track Details Modal
  const [selectedTrack, setSelectedTrack] = useState<Track | null>(null);

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
  const [spotifyPlaylists, setSpotifyPlaylists] = useState<YouTubePlaylist[]>(() => {
    const saved = localStorage.getItem('sp_playlists');
    return saved ? JSON.parse(saved) : [];
  });
  
  const [playlistsLoading, setPlaylistsLoading] = useState(false);
  
  const [selectedPlaylistId, setSelectedPlaylistId] = useState(() => {
    return localStorage.getItem('yt_selected_id') || '';
  });
  const [selectedSpPlaylistId, setSelectedSpPlaylistId] = useState(() => {
    return localStorage.getItem('sp_selected_id') || '';
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

  const fetchSpotifyPlaylists = useCallback(() => {
    if (!token || !status.spotify_connected) return;

    setPlaylistsLoading(true);
    fetch('/api/integrations/spotify/playlists', {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(async res => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to load Spotify playlists');
        return data;
      })
      .then(data => {
        const playlists = data.playlists || [];
        setSpotifyPlaylists(playlists);
        localStorage.setItem('sp_playlists', JSON.stringify(playlists));
        if (playlists.length > 0) {
          const firstId = playlists[0].id;
          setSelectedSpPlaylistId(firstId);
          localStorage.setItem('sp_selected_id', firstId);
        }
      })
      .catch(err => {
        setModal({
          show: true,
          type: 'error',
          title: 'Connection Failed',
          message: `We couldn't reach Spotify: ${err.message}.`
        });
      })
      .finally(() => setPlaylistsLoading(false));
  }, [token, status.spotify_connected]);

  const handleSpPlaylistChange = (id: string) => {
    setSelectedSpPlaylistId(id);
    localStorage.setItem('sp_selected_id', id);
  };

  const handlePlaylistChange = (id: string) => {
    setSelectedPlaylistId(id);
    localStorage.setItem('yt_selected_id', id);
  };

  const fetchTracks = useCallback(async (targetPage = page, silent = false) => {
    if (!token) return;
    if (!silent) setLoading(true);
    try {
      const q = new URLSearchParams({
        page: targetPage.toString(),
        page_size: PAGE_SIZE.toString(),
        sort_by: sortBy,
        sort_order: sortOrder
      });
      if (debouncedSearch) q.append('search', debouncedSearch);
      if (artistFilter) q.append('artist', artistFilter);
      if (genreFilter) q.append('genre', genreFilter);
      if (moodFilter) q.append('mood', moodFilter);
      if (activeTab === 'youtube') q.append('source', 'youtube');
      if (activeTab === 'spotify') q.append('source', 'spotify');

      const res = await fetch(`/api/music/library?${q}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Failed to fetch');
      const data = await res.json();
      setTracks(data.tracks || []);
      setTotal(data.total || 0);
      setTotalPages(data.total_pages || 0);
      setPage(data.page || targetPage);
    } catch (err) {
      console.error(err);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [token, page, debouncedSearch, artistFilter, genreFilter, moodFilter, sortBy, sortOrder, activeTab]);

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
  };

  useEffect(() => {
    if (token) {
      fetchTracks(page);
    }
    const interval = setInterval(() => {
      fetchTracks(page, true);
    }, 10000);
    return () => clearInterval(interval);
  }, [fetchTracks, page, token]);
  const [enriching, setEnriching] = useState(false);

  useEffect(() => {
    if (selectedTrack) {
      const needsLyrics = !selectedTrack.lyrics && !selectedTrack.lyrics_not_found;
      const needsClassification = !selectedTrack.genre || !selectedTrack.mood;
      
      if (needsLyrics || needsClassification) {
        let isMounted = true;
        const enrichTrack = async () => {
          if (isMounted) setEnriching(true);
          try {
            const res = await fetch(`/api/music/tracks/${selectedTrack.id}/enrich`, {
              headers: { Authorization: `Bearer ${token}` }
            });
            if (res.ok) {
              const updatedTrack = await res.json();
              if (isMounted) {
                setSelectedTrack((prev: any) => prev?.id === updatedTrack.id ? updatedTrack : prev);
                setTracks((prev) => prev.map(t => t.id === updatedTrack.id ? updatedTrack : t));
              }
            }
          } catch (e) {
            console.error("Failed to enrich track", e);
          } finally {
            if (isMounted) setEnriching(false);
          }
        };
        enrichTrack();
        return () => { isMounted = false; };
      }
    }
  }, [selectedTrack?.id, token]);

  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [lyricsTaskStatus, setLyricsTaskStatus] = useState<{message: string, progress: number, total: number} | null>(null);

  const pollTask = useCallback(async (taskId: string) => {
    if (!taskId) return;
    setActiveTaskId(taskId);
    
    let isMounted = true;
    const poll = async () => {
      if (!isMounted) return;
      try {
        const res = await fetch(`/api/tasks/${taskId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        
        if (!res.ok) {
           setImporting(false);
           setActiveTaskId(null);
           setLyricsTaskStatus(null);
           return;
        }
        
        const task = await res.json();

        if (task.status === 'completed') {
          setModal({
            show: true,
            type: 'success',
            title: 'Complete',
            message: `${task.result?.message || task.message || 'Finished successfully.'}`
          });
          setImporting(false);
          setActiveTaskId(null);
          setLyricsTaskStatus(null);
          fetchTracks(1, false); 
          return;
        }

        if (task.status === 'failed') {
          setModal({
            show: true,
            type: 'error',
            title: 'Failed',
            message: task.error || 'Something went wrong.'
          });
          setImporting(false);
          setActiveTaskId(null);
          setLyricsTaskStatus(null);
          return;
        }

        if (task.name === 'Fetch Lyrics') {
          setLyricsTaskStatus({ message: task.message, progress: task.progress, total: task.total });
        } else {
          setModal({
            show: true,
            type: 'info',
            title: task.name + ' in Progress',
            message: task.message + (task.total ? ` (${task.progress} / ${task.total})` : '')
          });
        }
        
        // Silently update the library table in the background so user sees tracks appearing
        if (isMounted) fetchTracks(page, true);

        if (isMounted) setTimeout(poll, 2000);
      } catch (err) {
        console.error('Polling error:', err);
        setImporting(false);
        setActiveTaskId(null);
        setLyricsTaskStatus(null);
      }
    };
    poll();
    return () => { isMounted = false; };
  }, [token, fetchTracks, page]);

  useEffect(() => {
    fetchStatus();
    if (token) {
      fetch('/api/tasks/active', {
        headers: { Authorization: `Bearer ${token}` }
      })
      .then(res => res.json())
      .then(data => {
        if (data.tasks && data.tasks.length > 0) {
           const t = data.tasks[0];
           if ((t.name.includes('Import') || t.name.includes('Sync') || t.name.includes('Lyrics')) && t.id !== activeTaskId) {
              pollTask(t.id);
           }
        }
      })
      .catch(console.error);
    }
  }, [fetchStatus, token, pollTask, activeTaskId]);

  const handleYouTubeImport = async () => {
    if (!token || !selectedPlaylistId) return;

    setImporting(true);
    setModal({ show: true, type: 'info', title: 'Import Started', message: 'Connecting to YouTube...' });

    try {
      const res = await fetch(`/api/integrations/youtube/import-playlist/${selectedPlaylistId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.task_id) pollTask(data.task_id);
      else throw new Error(data.detail || 'Failed');
    } catch (err: any) {
      setImporting(false);
      setModal({ show: true, type: 'error', title: 'Error', message: err.message });
    }
  };

  const handleSpotifyImport = async () => {
    if (!token || !selectedSpPlaylistId) return;

    setImporting(true);
    setModal({ show: true, type: 'info', title: 'Import Started', message: 'Connecting to Spotify...' });

    try {
      const res = await fetch(`/api/integrations/spotify/import-playlist/${selectedSpPlaylistId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.task_id) pollTask(data.task_id);
      else throw new Error(data.detail || 'Failed');
    } catch (err: any) {
      setImporting(false);
      setModal({ show: true, type: 'error', title: 'Error', message: err.message });
    }
  };

  const handleFetchLyrics = async () => {
    if (!token) return;
    setImporting(true);
    setLyricsTaskStatus({ message: "Starting...", progress: 0, total: 0 });
    try {
      const res = await fetch('/api/music/fetch-lyrics', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.task_id) pollTask(data.task_id);
      else setLyricsTaskStatus(null);
    } catch (err) {
      setImporting(false);
      setLyricsTaskStatus(null);
    }
  };

  const handleAIClassify = async () => {
    if (!token) return;
    setImporting(true);
    try {
      const res = await fetch('/api/music/classify-all', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.task_id) pollTask(data.task_id);
    } catch (err) {
      setImporting(false);
    }
  };

  const confirmDelete = (trackId: number, title: string) => {
    setModal({
      show: true,
      type: 'confirm',
      title: 'Remove Track',
      message: `Are you sure you want to remove "${title}"?`,
      confirmText: 'Remove',
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
    } catch (err) { console.error(err); }
  };

  const toggleSort = (field: string) => {
    if (sortBy === field) setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    else { setSortBy(field); setSortOrder('asc'); }
  };

  const pollClassifyTask = useCallback(async (taskId: string) => {
    const poll = async () => {
      try {
        const res = await fetch(`/api/tasks/${taskId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (!res.ok) { setIsClassifyingAi(false); return; }
        const task = await res.json();
        if (task.status === 'completed') {
          setModal({ show: true, type: 'success', title: 'Complete', message: task.result?.message || 'Success.' });
          setIsClassifyingAi(false);
          handlePageChange(1);
          return;
        }
        if (task.status === 'failed') {
          setModal({ show: true, type: 'error', title: 'Failed', message: task.error || 'Error.' });
          setIsClassifyingAi(false);
          return;
        }
        setModal({ show: true, type: 'info', title: 'Analyzing...', message: task.message + (task.total ? ` (${task.progress} / ${task.total})` : '') });
        setTimeout(poll, 5000);
      } catch (err) { setIsClassifyingAi(false); }
    };
    poll();
  }, [token, handlePageChange]);

  const handleClassifyAi = async () => {
    if (!token) return;
    setIsClassifyingAi(true);
    setModal({ show: true, type: 'info', title: 'AI classification', message: 'Gemini is working in the background...' });
    try {
      const res = await fetch('/api/music/classify-all', { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (res.ok && data.task_id) pollClassifyTask(data.task_id);
      else setIsClassifyingAi(false);
    } catch (err) { setIsClassifyingAi(false); }
  };

  const startBatchNormalize = async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch('/api/music/normalize/preview', { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      setPreviewData(data.preview || []);
      setSelectedForBatch(new Set((data.preview || []).map((p: NormalizePreview) => p.id)));
      setShowBatchModal(true);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  const handleBatchCommit = async () => {
    if (!token || selectedForBatch.size === 0) return;
    setIsBatchProcessing(true);
    try {
      const res = await fetch('/api/music/normalize/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ track_ids: Array.from(selectedForBatch) })
      });
      if (res.ok) { setShowBatchModal(false); handlePageChange(page); }
    } catch (err) { console.error(err); }
    finally { setIsBatchProcessing(false); }
  };

  const toggleBatchTrack = (id: number) => {
    const next = new Set(selectedForBatch);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedForBatch(next);
  };

  const clearFilters = () => { setSearch(''); setArtistFilter(''); setGenreFilter(''); setMoodFilter(''); };

  const renderSortIndicator = (field: string) => {
    if (sortBy !== field) return null;
    return sortOrder === 'asc' ? <ArrowUp className="w-3 h-3 ml-1 text-primary" /> : <ArrowDown className="w-3 h-3 ml-1 text-primary" />;
  };

  return (
    <div className="max-w-7xl mx-auto px-1 sm:px-2 md:px-0 space-y-6 md:space-y-8 animate-in fade-in duration-500 pb-20">
      {/* Platform Switcher Tabs */}
      <div className="flex p-1 bg-gray-200/50 rounded-2xl w-fit">
        <button onClick={() => setActiveTab('all')} className={`px-6 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${activeTab === 'all' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
          Central Hub
        </button>
        <button onClick={() => setActiveTab('youtube')} className={`px-6 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all flex items-center gap-2 ${activeTab === 'youtube' ? 'bg-white text-red-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
          <Music2 className="w-3 h-3" /> YouTube Music
        </button>
        <button onClick={() => setActiveTab('spotify')} className={`px-6 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all flex items-center gap-2 ${activeTab === 'spotify' ? 'bg-white text-green-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
          <Globe className="w-3 h-3" /> Spotify
        </button>
      </div>

      {/* Page Header */}
      <header className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 md:gap-6">
        <div>
          <h1 className="text-3xl font-black text-gray-900 tracking-tight">
            {activeTab === 'all' ? 'Golden Library' : activeTab === 'youtube' ? 'YT Music Collection' : 'Spotify Library'}
          </h1>
          <p className="text-sm md:text-base text-gray-500 font-medium">Managing {total} tracks from {activeTab}.</p>
        </div>
        
        <div className="flex flex-wrap items-center gap-3">
          {activeTab === 'all' && (
            <>
              <button onClick={handleFetchLyrics} disabled={importing || !!lyricsTaskStatus} className="flex-1 lg:flex-none flex items-center justify-center gap-2 bg-white text-gray-900 px-5 py-3 rounded-2xl border border-gray-200 shadow-sm hover:shadow-md hover:border-primary/30 transition-all font-bold text-sm group disabled:opacity-50">
                <Music2 className="w-4 h-4 text-primary" /> 
                {lyricsTaskStatus ? 'Fetching...' : 'Get Lyrics'}
              </button>
              <button onClick={handleAIClassify} disabled={importing} className="flex-1 lg:flex-none flex items-center justify-center gap-2 bg-gray-900 text-white px-5 py-3 rounded-2xl shadow-xl shadow-gray-900/10 hover:bg-gray-800 transition-all font-bold text-sm group disabled:opacity-50">
                <Brain className="w-4 h-4 text-primary" /> Classify (AI)
              </button>
              <button 
                onClick={async () => {
                  if(!token) return;
                  setIsCleaning(true);
                  try {
                    const res = await fetch('/api/music/clean-database', { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } });
                    const data = await res.json();
                    if(res.ok) {
                      setModal({ show: true, type: 'success', title: 'Database Cleaned', message: data.message });
                      fetchTracks(page, search);
                    }
                  } catch (e) {
                    console.error(e);
                  } finally {
                    setIsCleaning(false);
                  }
                }}
                disabled={importing || isCleaning} 
                className="flex-1 lg:flex-none flex items-center justify-center gap-2 bg-red-50 text-red-600 px-5 py-3 rounded-2xl shadow-sm border border-red-100 hover:bg-red-100 transition-all font-bold text-sm group disabled:opacity-50"
              >
                {isCleaning ? <Loader2 className="w-4 h-4 animate-spin text-red-500" /> : <Sparkles className="w-4 h-4 text-red-500" />}
                {isCleaning ? 'Cleaning...' : 'Clean Database'}
              </button>
            </>
          )}

          {activeTab === 'youtube' && status.youtube_connected && (
            <div className="flex-1 lg:flex-none flex items-stretch gap-2 bg-white p-1.5 rounded-2xl border border-gray-200 shadow-sm min-w-[300px]">
              {youtubePlaylists.length === 0 ? (
                <button onClick={fetchYouTubePlaylists} disabled={playlistsLoading} className="flex-1 flex items-center justify-center gap-2 py-2 text-sm font-black text-gray-400 hover:text-primary transition-colors"><RefreshCw className={`w-4 h-4 ${playlistsLoading ? 'animate-spin' : ''}`} /> Fetch Playlists</button>
              ) : (
                <div className="flex items-center gap-1 w-full min-w-0">
                  <div className="flex-1 flex items-center px-2 min-w-0 bg-gray-50 rounded-xl h-10">
                    <Music2 className="w-4 h-4 text-primary mr-2 flex-shrink-0" />
                    <select value={selectedPlaylistId} onChange={(e) => handlePlaylistChange(e.target.value)} className="bg-transparent text-[13px] font-bold focus:outline-none w-full truncate appearance-none">
                      {youtubePlaylists.map((p) => {
                        const isLiked = p.id === '__liked_videos__';
                        const countLabel = isLiked && p.track_count === 0 ? 'Ready to Import' : `${p.track_count} synced`;
                        return <option key={p.id} value={p.id}>{p.title} ({countLabel})</option>;
                      })}
                    </select>
                  </div>
                  <button onClick={handleYouTubeImport} disabled={importing} className="bg-gray-900 text-white px-5 h-10 rounded-xl text-[11px] font-black uppercase tracking-wider hover:bg-gray-800 disabled:opacity-50">Import</button>
                  <button onClick={fetchYouTubePlaylists} className="p-2.5 text-gray-400 hover:text-primary rounded-xl bg-gray-50"><RefreshCw className={`w-4 h-4 ${playlistsLoading ? 'animate-spin' : ''}`} /></button>
                </div>
              )}
            </div>
          )}

          {activeTab === 'spotify' && status.spotify_connected && (
             <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                <div className="flex-1 sm:flex-none flex items-stretch gap-2 bg-white p-1.5 rounded-2xl border border-gray-200 shadow-sm min-w-[300px]">
                  {spotifyPlaylists.length === 0 ? (
                    <button onClick={fetchSpotifyPlaylists} disabled={playlistsLoading} className="flex-1 flex items-center justify-center gap-2 py-2 text-sm font-black text-gray-400 hover:text-green-600 transition-colors"><RefreshCw className={`w-4 h-4 ${playlistsLoading ? 'animate-spin' : ''}`} /> Fetch Playlists</button>
                  ) : (
                    <div className="flex items-center gap-1 w-full min-w-0">
                      <div className="flex-1 flex items-center px-2 min-w-0 bg-gray-50 rounded-xl h-10">
                        <Globe className="w-4 h-4 text-green-600 mr-2 flex-shrink-0" />
                        <select value={selectedSpPlaylistId} onChange={(e) => handleSpPlaylistChange(e.target.value)} className="bg-transparent text-[13px] font-bold focus:outline-none w-full truncate appearance-none">
                          {spotifyPlaylists.map((p) => <option key={p.id} value={p.id}>{p.title} ({p.track_count})</option>)}
                        </select>
                      </div>
                      <button onClick={handleSpotifyImport} disabled={importing} className="bg-green-600 text-white px-5 h-10 rounded-xl text-[11px] font-black uppercase tracking-wider hover:bg-green-700 disabled:opacity-50">Import</button>
                      <button onClick={fetchSpotifyPlaylists} className="p-2.5 text-gray-400 hover:text-green-600 rounded-xl bg-gray-50"><RefreshCw className={`w-4 h-4 ${playlistsLoading ? 'animate-spin' : ''}`} /></button>
                    </div>
                  )}
                </div>
             </div>
          )}
        </div>
      </header>

      {/* Control Bar */}
      <div className="sticky top-[72px] lg:top-4 z-20 bg-white/90 backdrop-blur-xl border border-gray-100 rounded-3xl shadow-lg shadow-gray-200/20 p-2">
        <div className="flex flex-col md:flex-row items-stretch md:items-center gap-2">
          <div className="flex-1 relative group">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 group-focus-within:text-primary transition-colors" />
            <input type="text" placeholder="Search title, artist..." value={search} onChange={(e) => setSearch(e.target.value)} className="w-full bg-gray-50/50 border-none rounded-2xl pl-11 pr-4 py-3 text-sm font-medium focus:ring-2 focus:ring-primary/10 outline-none transition-all" />
          </div>
          <div className="flex items-center gap-2 overflow-x-auto no-scrollbar">
            <input type="text" placeholder="Artist..." value={artistFilter} onChange={(e) => setArtistFilter(e.target.value)} className="w-36 bg-gray-50/50 border-none rounded-2xl px-4 py-3 text-sm font-medium focus:ring-2 focus:ring-primary/10 outline-none" />
            <select value={genreFilter} onChange={(e) => setGenreFilter(e.target.value)} className="w-36 bg-gray-50/50 border-none rounded-2xl px-4 py-3 text-sm font-medium focus:ring-2 focus:ring-primary/10 outline-none appearance-none">
              <option value="">All Genres</option>
              <option value="Pop">Pop</option>
              <option value="Bollywood">Bollywood</option>
              <option value="Rock">Rock</option>
              <option value="Indie">Indie</option>
            </select>
            {(search || artistFilter || genreFilter || moodFilter) && <button onClick={clearFilters} className="px-4 py-2 text-sm font-bold text-red-500 hover:bg-red-50 rounded-xl">Clear</button>}
          </div>
        </div>
      </div>

      {/* Real-time Lyrics Fetching Banner */}
      {lyricsTaskStatus && (
        <div className="bg-primary/5 border border-primary/10 rounded-[24px] p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 shadow-sm animate-in fade-in slide-in-from-top-4 duration-500">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl bg-white shadow-sm flex items-center justify-center border border-primary/10">
               <Loader2 className="w-5 h-5 text-primary animate-spin" />
            </div>
            <div>
              <h4 className="text-sm font-black text-gray-900 tracking-tight">{lyricsTaskStatus.message || "Fetching Lyrics..."}</h4>
              <p className="text-xs font-bold text-gray-500 mt-0.5">
                {lyricsTaskStatus.total > 0 ? `Processed ${lyricsTaskStatus.progress} of ${lyricsTaskStatus.total} tracks` : 'Warming up engines...'}
              </p>
            </div>
          </div>
          {lyricsTaskStatus.total > 0 && (
             <div className="w-full md:w-64 h-3 bg-white rounded-full overflow-hidden shadow-inner border border-gray-100">
                <div 
                  className="h-full bg-primary transition-all duration-500 ease-out" 
                  style={{ width: `${(lyricsTaskStatus.progress / lyricsTaskStatus.total) * 100}%` }}
                />
             </div>
          )}
        </div>
      )}

      {/* Table Hub */}
      <div className="bg-white rounded-[32px] border border-gray-100 shadow-xl shadow-gray-200/40 overflow-hidden">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-gray-50 bg-gray-50/30 text-[11px] font-black text-gray-400 uppercase tracking-widest">
              <th onClick={() => toggleSort('title')} className="pl-8 pr-4 py-5 cursor-pointer hover:text-primary select-none"><div className="flex items-center">Track Info {renderSortIndicator('title')}</div></th>
              <th className="px-4 py-5">Source</th>
              <th onClick={() => toggleSort('genre')} className="px-4 py-5 cursor-pointer hover:text-primary select-none"><div className="flex items-center">Insights {renderSortIndicator('genre')}</div></th>
              <th className="px-4 py-5 text-center"><Clock className="w-3.5 h-3.5 mx-auto" /></th>
              <th onClick={() => toggleSort('created_at')} className="pl-4 pr-8 py-5 cursor-pointer hover:text-primary select-none text-right"><div className="flex items-center justify-end">Added {renderSortIndicator('created_at')}</div></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading ? [...Array(6)].map((_, i) => <tr key={i} className="animate-pulse"><td colSpan={5} className="px-8 py-6"><div className="flex gap-4"><div className="w-12 h-12 bg-gray-100 rounded-xl" /><div className="flex-1 space-y-2"><div className="h-4 bg-gray-100 rounded w-1/4" /><div className="h-3 bg-gray-50 rounded w-1/6" /></div></div></td></tr>) : tracks.length === 0 ? <tr><td colSpan={5} className="px-8 py-20 text-center"><p className="font-bold text-gray-400">Library Empty</p></td></tr> : tracks.map((track) => (
              <tr key={track.id} className="group hover:bg-primary/[0.02] transition-all cursor-pointer" onClick={() => setSelectedTrack(track)}>
                <td className="pl-8 pr-4 py-4">
                  <div className="flex items-center gap-4">
                    <div className="relative w-14 h-14 rounded-2xl overflow-hidden bg-gray-100 shadow-sm group-hover:scale-105 transition-transform duration-300">
                      <img src={track.thumbnail_url || ''} alt="" className="w-full h-full object-cover" />
                      <div className="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                        <Loader2 className="w-5 h-5 text-white animate-spin opacity-40" />
                      </div>
                    </div>
                    <div className="min-w-0">
                      <p className="font-black text-gray-900 truncate leading-tight">{track.title}</p>
                      <p className="text-xs font-bold text-gray-400 truncate">{track.artist}</p>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-4">
                  <div className="flex gap-2">
                    {track.source === 'youtube' ? <div className="w-8 h-8 bg-red-50 rounded-lg flex items-center justify-center text-red-500 shadow-sm border border-red-100"><Music2 className="w-4 h-4" /></div> : <div className="w-8 h-8 bg-green-50 rounded-lg flex items-center justify-center text-green-500 shadow-sm border border-green-100"><Globe className="w-4 h-4" /></div>}
                    {track.spotify_uri && track.source === 'youtube' && <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center text-blue-500 shadow-sm border border-blue-100" title="Matched to Spotify"><Zap className="w-4 h-4" /></div>}
                  </div>
                </td>
                <td className="px-4 py-4">
                   <div className="flex items-center gap-3">
                      <div className="flex flex-col gap-1">
                        <div className="flex flex-wrap gap-1">
                          {track.genre && <span className="text-[9px] px-1.5 py-0.5 bg-purple-50 text-purple-600 rounded-md font-black uppercase tracking-widest">{track.genre.split(',')[0]}</span>}
                          {track.themes && <span className="text-[9px] px-1.5 py-0.5 bg-amber-50 text-amber-600 rounded-md font-black uppercase tracking-widest">{track.themes.split(',')[0]}</span>}
                          {track.emotions && <span className="text-[9px] px-1.5 py-0.5 bg-rose-50 text-rose-600 rounded-md font-black uppercase tracking-widest">{track.emotions.split(',')[0]}</span>}
                          {!track.genre && !track.themes && <span className="text-[9px] px-1.5 py-0.5 bg-gray-50 text-gray-400 rounded-md font-black uppercase tracking-widest">UNCLASSIFIED</span>}
                        </div>
                        <div className="w-16 h-1 bg-gray-100 rounded-full overflow-hidden mt-1">
                           <div className="bg-primary h-full transition-all" style={{ width: `${(track.energy || 0.5) * 100}%` }} />
                        </div>
                      </div>
                      {track.lyrics && <span title="Lyrics available"><Mic className="w-4 h-4 text-purple-400" /></span>}
                   </div>
                </td>
                <td className="px-4 py-4 text-center text-sm font-black text-gray-400 tabular-nums">{formatDuration(track.duration_ms)}</td>
                <td className="pl-4 pr-8 py-4 text-right">
                   <div className="flex items-center justify-end gap-2">
                      <span className="text-xs font-bold text-gray-300">{formatDate(track.created_at)}</span>
                      <button onClick={(e) => { e.stopPropagation(); confirmDelete(track.id, track.title); }} className="opacity-0 group-hover:opacity-100 p-2 text-red-400 hover:bg-red-50 rounded-xl transition-all"><Trash2 className="w-4 h-4" /></button>
                   </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between px-4 py-4">
        <div className="text-xs font-black text-gray-400 uppercase tracking-widest">{total} Total</div>
        <div className="flex items-center gap-2">
          <button onClick={() => handlePageChange(Math.max(1, page - 1))} disabled={page <= 1} className="w-12 h-12 flex items-center justify-center rounded-2xl bg-white border border-gray-200 text-gray-600 disabled:opacity-20 hover:shadow-md transition-all"><ChevronLeft className="w-5 h-5" /></button>
          <div className="bg-gray-900 text-white px-4 h-12 flex items-center rounded-2xl font-black text-sm shadow-lg">
            <input 
              type="number" 
              value={page}
              onChange={(e) => {
                 const val = parseInt(e.target.value);
                 if (val > 0 && val <= totalPages) {
                    handlePageChange(val);
                 }
              }}
              className="bg-transparent w-8 text-center outline-none border-b border-gray-700 focus:border-white transition-colors hide-spin-button"
            />
            <span className="mx-2 opacity-50">/</span> {totalPages}
          </div>
          <button onClick={() => handlePageChange(Math.min(totalPages, page + 1))} disabled={page >= totalPages} className="w-12 h-12 flex items-center justify-center rounded-2xl bg-white border border-gray-200 text-gray-600 disabled:opacity-20 hover:shadow-md transition-all"><ChevronRight className="w-5 h-5" /></button>
        </div>
      </div>

      {/* Track Modal */}
      {selectedTrack && (
        <div className="fixed inset-0 z-[150] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-950/80 backdrop-blur-md" onClick={() => setSelectedTrack(null)} />
          <div className="relative bg-white w-full max-w-4xl max-h-[90vh] rounded-[40px] shadow-2xl overflow-hidden flex flex-col animate-in fade-in zoom-in duration-300">
            <div className="px-8 py-6 border-b border-gray-50 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center text-primary"><Music2 className="w-6 h-6" /></div>
                <div><h2 className="text-xl font-black text-gray-900">{selectedTrack.title}</h2><p className="text-sm font-bold text-gray-400 uppercase tracking-widest">{selectedTrack.artist}</p></div>
              </div>
              <button onClick={() => setSelectedTrack(null)} className="p-3 bg-gray-50 hover:bg-gray-100 rounded-full transition-all"><X className="w-6 h-6 text-gray-400" /></button>
            </div>
            <div className="flex-1 overflow-y-auto p-10 grid grid-cols-1 lg:grid-cols-2 gap-10">
              <div className="space-y-8">
                <img src={selectedTrack.thumbnail_url || ''} alt="" className="aspect-square w-full rounded-[32px] object-cover shadow-xl" />
                
                {/* Classification Data */}
                <div className="space-y-4">
                  <div className="flex items-center gap-2 mb-4">
                    <Activity className="w-4 h-4 text-primary" />
                    <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Smart Classification</span>
                    {enriching && <Loader2 className="w-3 h-3 animate-spin text-primary ml-auto" />}
                  </div>
                  
                  <div className="flex flex-wrap gap-2">
                    {/* Genre Tags */}
                    {selectedTrack.genre && selectedTrack.genre.split(',').map((g: string, i: number) => (
                      <span key={`genre-${i}`} className="px-4 py-2 bg-purple-50 text-purple-600 rounded-full text-xs font-bold uppercase tracking-wider border border-purple-100">
                        {g.trim()}
                      </span>
                    ))}
                    
                    {/* Mood Tags */}
                    {selectedTrack.mood && selectedTrack.mood.split(',').map((m: string, i: number) => (
                      <span key={`mood-${i}`} className="px-4 py-2 bg-blue-50 text-blue-600 rounded-full text-xs font-bold uppercase tracking-wider border border-blue-100">
                        {m.trim()}
                      </span>
                    ))}

                    {/* Theme Tags */}
                    {selectedTrack.themes && selectedTrack.themes.split(',').map((t: string, i: number) => (
                      <span key={`theme-${i}`} className="px-4 py-2 bg-amber-50 text-amber-600 rounded-full text-xs font-bold uppercase tracking-wider border border-amber-100">
                        {t.trim()}
                      </span>
                    ))}

                    {/* Emotion Tags */}
                    {selectedTrack.emotions && selectedTrack.emotions.split(',').map((e: string, i: number) => (
                      <span key={`emotion-${i}`} className="px-4 py-2 bg-rose-50 text-rose-600 rounded-full text-xs font-bold uppercase tracking-wider border border-rose-100">
                        {e.trim()}
                      </span>
                    ))}

                    {/* Context Tags */}
                    {selectedTrack.contexts && selectedTrack.contexts.split(',').map((c: string, i: number) => (
                      <span key={`context-${i}`} className="px-4 py-2 bg-emerald-50 text-emerald-600 rounded-full text-xs font-bold uppercase tracking-wider border border-emerald-100">
                        {c.trim()}
                      </span>
                    ))}
                    
                    {/* Release Year */}
                    {selectedTrack.release_year && (
                      <span className="px-4 py-2 bg-gray-50 text-gray-600 rounded-full text-xs font-bold uppercase tracking-wider border border-gray-200">
                        {selectedTrack.release_year}
                      </span>
                    )}

                    {/* Popularity */}
                    {selectedTrack.popularity !== undefined && selectedTrack.popularity !== null && (
                      <span className="px-4 py-2 bg-orange-50 text-orange-600 rounded-full text-xs font-bold uppercase tracking-wider border border-orange-100 flex items-center gap-1">
                        <Zap className="w-3 h-3" /> {selectedTrack.popularity} Pop
                      </span>
                    )}
                    
                    {/* Explicit */}
                    {selectedTrack.explicit && (
                      <span className="px-4 py-2 bg-red-50 text-red-600 rounded-full text-xs font-bold uppercase tracking-wider border border-red-100 flex items-center gap-1">
                        <X className="w-3 h-3" /> Explicit
                      </span>
                    )}

                    {!selectedTrack.genre && !selectedTrack.mood && !enriching && (
                      <span className="text-xs font-bold text-gray-400">No classification data available</span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex flex-col min-h-[400px]">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-3"><Mic className="w-5 h-5 text-gray-400" /><h4 className="text-sm font-black text-gray-900 uppercase tracking-[0.2em]">Lyrics</h4></div>
                  {enriching && <Loader2 className="w-5 h-5 animate-spin text-gray-400" />}
                </div>
                <div className="flex-1 bg-gray-50 rounded-[32px] p-8 border border-gray-100 overflow-y-auto">
                  {selectedTrack.lyrics ? (
                    <pre className="text-sm font-bold text-gray-600 leading-relaxed whitespace-pre-wrap font-sans">{selectedTrack.lyrics}</pre>
                  ) : enriching ? (
                    <div className="h-full flex flex-col items-center justify-center text-center opacity-40">
                      <Loader2 className="w-10 h-10 animate-spin mb-4" />
                      <p className="text-xs font-black uppercase">Fetching lyrics...</p>
                    </div>
                  ) : selectedTrack.lyrics_not_found ? (
                    <div className="h-full flex flex-col items-center justify-center text-center opacity-40 text-gray-500">
                       <Mic className="w-10 h-10 mb-4 opacity-50" />
                       <p className="text-xs font-black uppercase">No lyrics found for this track</p>
                    </div>
                  ) : (
                    <div className="h-full flex flex-col items-center justify-center text-center opacity-40 text-gray-500">
                       <Mic className="w-10 h-10 mb-4 opacity-50" />
                       <p className="text-xs font-black uppercase">No lyrics available</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Global Feedback Modal System */}
      {modal.show && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-950/60 backdrop-blur-sm" onClick={() => modal.type !== 'confirm' && setModal({ ...modal, show: false })} />
          <div className="relative bg-white w-full max-w-sm rounded-[32px] shadow-2xl p-8 animate-in fade-in zoom-in duration-200">
            <div className="flex flex-col items-center text-center">
              <div className={`w-20 h-20 rounded-full flex items-center justify-center mb-6 ${modal.type === 'error' ? 'bg-red-50 text-red-500' : modal.type === 'success' ? 'bg-green-50 text-green-500' : modal.type === 'confirm' ? 'bg-orange-50 text-orange-500' : 'bg-blue-50 text-primary'}`}>
                {modal.type === 'error' && <AlertCircle className="w-10 h-10" />}
                {modal.type === 'success' && <CheckCircle2 className="w-8 h-8 sm:w-10 sm:h-10" />}
                {modal.type === 'confirm' && <Trash2 className="w-10 h-10" />}
                {modal.type === 'info' && <Info className="w-8 h-8 sm:w-10 sm:h-10" />}
              </div>
              <h3 className="text-2xl font-black text-gray-900 mb-2">{modal.title}</h3>
              <p className="text-sm text-gray-500 font-medium mb-8 leading-relaxed">{modal.message}</p>
              <div className="flex items-center gap-3 w-full">
                {modal.type === 'confirm' ? (
                  <><button onClick={() => setModal({ ...modal, show: false })} className="flex-1 px-6 h-14 rounded-2xl text-sm font-black text-gray-400 hover:bg-gray-50 transition">Cancel</button>
                  <button onClick={modal.onConfirm} className="flex-1 px-6 h-14 rounded-2xl text-sm font-black bg-red-500 text-white shadow-lg shadow-red-500/20">Confirm</button></>
                ) : <button onClick={() => setModal({ ...modal, show: false })} className="w-full px-6 h-14 rounded-2xl text-sm font-black bg-gray-900 text-white">Close</button>}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Batch Normalize Modal */}
      {showBatchModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-950/80 backdrop-blur-md" onClick={() => setShowBatchModal(false)} />
          <div className="relative bg-white w-full max-w-4xl max-h-[85vh] rounded-[40px] shadow-2xl overflow-hidden flex flex-col animate-in fade-in zoom-in duration-300">
            <div className="px-10 py-8 border-b border-gray-50 flex items-center justify-between">
              <div><h2 className="text-3xl font-black text-gray-900">Bulk Clean-up</h2><p className="text-sm text-gray-500">detected {previewData.length} tracks.</p></div>
              <button onClick={() => setShowBatchModal(false)} className="p-3 bg-gray-50 hover:bg-gray-100 rounded-full"><X className="w-6 h-6 text-gray-400" /></button>
            </div>
            <div className="flex-1 overflow-y-auto p-10 space-y-6">
              {previewData.map((item) => (
                <div key={item.id} onClick={() => toggleBatchTrack(item.id)} className={`group flex items-center gap-6 p-6 rounded-[24px] border-2 transition-all cursor-pointer ${selectedForBatch.has(item.id) ? 'border-primary bg-primary/[0.02]' : 'border-gray-50 bg-gray-50/30 opacity-50grayscale'}`}>
                  <div className={`w-10 h-10 rounded-xl border-2 flex items-center justify-center transition-all ${selectedForBatch.has(item.id) ? 'bg-primary border-primary text-white scale-110 shadow-lg' : 'bg-white border-gray-200 text-transparent'}`}><Check className="w-6 h-6" strokeWidth={4} /></div>
                  <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-10">
                    <div><span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Original</span><p className="text-sm font-bold text-gray-500 line-through decoration-red-400">{item.current_title}</p></div>
                    <div><span className="text-[10px] font-black text-primary uppercase tracking-widest">Magic Fix</span><p className="text-sm font-black text-gray-900">{item.proposed_title}</p></div>
                  </div>
                </div>
              ))}
            </div>
            <div className="px-10 py-8 bg-gray-50/50 flex items-center justify-between">
              <div className="text-sm font-black text-gray-400 uppercase tracking-widest"><span className="text-primary">{selectedForBatch.size}</span> Items Selected</div>
              <div className="flex items-center gap-4"><button onClick={() => setShowBatchModal(false)} className="px-8 h-14 text-sm font-black text-gray-500">Cancel</button><button onClick={handleBatchCommit} disabled={isBatchProcessing || selectedForBatch.size === 0} className="bg-primary text-white px-12 h-14 rounded-[20px] font-black shadow-xl shadow-primary/20 hover:bg-blue-600 transition-all">{isBatchProcessing ? 'Applying...' : 'Apply Changes'}</button></div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Library;
