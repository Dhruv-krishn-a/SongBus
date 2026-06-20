import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  Sparkles, Send, CheckCircle2, AlertCircle, 
  ExternalLink, Loader2, Music2, Info, Plus, Trash2, ListMusic, X, ChevronRight
} from 'lucide-react';

type ModalConfig = {
  show: boolean;
  type: 'info' | 'success' | 'error';
  title: string;
  message: string;
  link?: string;
  linkLabel?: string;
  buttonClass?: string;
};

interface PlaylistData {
  id: number;
  name: string;
  source: string;
  external_id?: string;
}

interface TrackData {
  id: number;
  title: string;
  artist: string;
  thumbnail_url: string;
  genre: string;
  mood: string;
  themes?: string;
  emotions?: string;
  contexts?: string;
}

interface PlatformSyncStatus {
  spotify?: string;
  ytmusic?: string;
}

function parseExternalId(externalId?: string, source?: string): PlatformSyncStatus {
  if (!externalId) return {};
  if (externalId.startsWith('plat:')) {
    const status: PlatformSyncStatus = {};
    const parts = externalId.slice(5).split(';');
    for (const part of parts) {
      const [platform, id] = part.split('=');
      if (platform === 'spotify' || platform === 'ytmusic') {
        status[platform] = id;
      }
    }
    return status;
  }
  if (source === 'spotify') return { spotify: externalId };
  if (source === 'youtube' || source === 'ytmusic') return { ytmusic: externalId };
  return { spotify: externalId };
}

export default function Playlists() {
  const { token } = useAuth();
  const [playlists, setPlaylists] = useState<PlaylistData[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [exportingId, setExportingId] = useState<number | null>(null);
  const [exportingPlaylist, setExportingPlaylist] = useState<PlaylistData | null>(null);
  const [showExportAllModal, setShowExportAllModal] = useState(false);
  const [exportingAll, setExportingAll] = useState(false);

  // View Tracks Modal
  const [viewingPlaylist, setViewingPlaylist] = useState<PlaylistData | null>(null);
  const [playlistTracks, setPlaylistTracks] = useState<TrackData[]>([]);
  const [loadingTracks, setLoadingTracks] = useState(false);

  // Create Mix Modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newMixName, setNewMixName] = useState('');
  const [newMixGenres, setNewMixGenres] = useState('');
  const [newMixMoods, setNewMixMoods] = useState('');
  const [creatingMix, setCreatingMix] = useState(false);

  const [modal, setModal] = useState<ModalConfig>({
    show: false,
    type: 'info',
    title: '',
    message: ''
  });

  const fetchPlaylists = useCallback(() => {
    if (!token) return;
    const timeoutId = setTimeout(() => setLoading(true), 0);
    fetch('/api/music/playlists', {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(res => res.json())
    .then(data => {
      setPlaylists(data.playlists || []);
      setLoading(false);
      clearTimeout(timeoutId);
    })
    .catch((err) => {
      console.error(err);
      setLoading(false);
      clearTimeout(timeoutId);
    });
  }, [token]);

  useEffect(() => {
    fetchPlaylists();
  }, [fetchPlaylists]);

  const handleGenerate = async () => {
    if (!token) return;
    setGenerating(true);
    try {
      const res = await fetch('/api/music/generate-playlists', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        setModal({
          show: true,
          type: 'success',
          title: 'Intelligence Active',
          message: data.message
        });
        fetchPlaylists();
      } else {
        setModal({
          show: true,
          type: 'error',
          title: 'Generation Failed',
          message: data.detail || 'Could not group tracks.'
        });
      }
    } catch (err) {
      console.error(err);
    } finally {
      setGenerating(false);
    }
  };

  const handleCreateCustomMix = async () => {
    if (!token || !newMixName) return;
    setCreatingMix(true);
    try {
      const res = await fetch('/api/music/playlists/custom', {
        method: 'POST',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: newMixName,
          genres: newMixGenres ? newMixGenres.split(',').map(s => s.trim()).filter(Boolean) : [],
          moods: newMixMoods ? newMixMoods.split(',').map(s => s.trim()).filter(Boolean) : []
        })
      });
      const data = await res.json();
      if (res.ok) {
        setShowCreateModal(false);
        setNewMixName('');
        setNewMixGenres('');
        setNewMixMoods('');
        setModal({
          show: true,
          type: 'success',
          title: 'Mix Created!',
          message: data.message
        });
        fetchPlaylists();
      } else {
        setModal({
          show: true,
          type: 'error',
          title: 'Failed to Create Mix',
          message: data.detail || 'No tracks matched your rules.'
        });
      }
    } catch (err) {
      console.error(err);
    } finally {
      setCreatingMix(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation(); // Prevent opening the tracks modal
    if (!token) return;
    if (!window.confirm("Are you sure you want to delete this mix?")) return;
    
    try {
      const res = await fetch(`/api/music/playlists/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        fetchPlaylists();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const viewTracks = async (pl: PlaylistData) => {
    setViewingPlaylist(pl);
    setLoadingTracks(true);
    try {
      const res = await fetch(`/api/music/playlists/${pl.id}/tracks`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setPlaylistTracks(data.tracks || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingTracks(false);
    }
  };

  const handleExportClick = (e: React.MouseEvent, pl: PlaylistData) => {
    e.stopPropagation();
    setExportingPlaylist(pl);
  };

  const handleExport = async (id: number, platform: 'spotify' | 'ytmusic') => {
    if (!token) return;
    setExportingPlaylist(null);
    setExportingId(id);
    try {
      const endpoint = platform === 'spotify' 
        ? `/api/music/export-spotify/${id}` 
        : `/api/music/export-ytmusic/${id}`;
        
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      
      const platformName = platform === 'spotify' ? 'Spotify' : 'YouTube Music';
      const linkLabel = platform === 'spotify' ? 'Open on Spotify' : 'Open on YouTube Music';
      const bgButtonClass = platform === 'spotify' ? 'bg-green-500 hover:bg-green-600' : 'bg-red-600 hover:bg-red-700';
      
      if (res.ok) {
        setModal({
          show: true,
          type: 'success',
          title: `Synced to ${platformName}`,
          message: `Matched ${data.matched} out of ${data.total} tracks. Your playlist is now live on your ${platformName} account!`,
          link: data.playlist_url,
          linkLabel: linkLabel,
          buttonClass: bgButtonClass
        });
        fetchPlaylists();
      } else {
        setModal({
          show: true,
          type: 'error',
          title: 'Export Failed',
          message: data.detail || `Visit Settings to connect ${platformName}.`
        });
      }
    } catch (err) {
      console.error(err);
    } finally {
      setExportingId(null);
    }
  };

  const handleExportAll = async (platform: 'spotify' | 'ytmusic') => {
    if (!token) return;
    setShowExportAllModal(false);
    setExportingAll(true);
    try {
      const res = await fetch(`/api/music/export-all/${platform}`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      
      const platformName = platform === 'spotify' ? 'Spotify' : 'YouTube Music';
      const bgButtonClass = platform === 'spotify' ? 'bg-green-500 hover:bg-green-600' : 'bg-red-600 hover:bg-red-700';
      
      if (res.ok) {
        setModal({
          show: true,
          type: 'success',
          title: `Bulk Export Complete`,
          message: data.message,
          buttonClass: bgButtonClass
        });
        fetchPlaylists();
      } else {
        setModal({
          show: true,
          type: 'error',
          title: 'Bulk Export Failed',
          message: data.detail || `Failed to export all playlists to ${platformName}.`
        });
      }
    } catch (err) {
      console.error(err);
      setModal({
        show: true,
        type: 'error',
        title: 'Bulk Export Error',
        message: 'An error occurred during bulk export. Please try again.'
      });
    } finally {
      setExportingAll(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 md:px-0 animate-in fade-in duration-500 pb-20">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
        <div>
          <h1 className="text-3xl font-black text-gray-900 tracking-tight">Smart Mixes</h1>
          <p className="text-gray-500 font-medium mt-1">AI-powered grouping of your music library.</p>
        </div>
        <div className="flex gap-4">
          <button 
            onClick={() => setShowExportAllModal(true)}
            disabled={exportingAll}
            className="flex items-center gap-2 bg-white text-gray-900 border border-gray-200 px-6 py-4 rounded-2xl font-black text-sm shadow-sm hover:border-gray-300 hover:bg-gray-50 transition-all active:scale-95 disabled:opacity-50"
          >
            {exportingAll ? (
              <Loader2 className="w-5 h-5 animate-spin text-primary" />
            ) : (
              <Send className="w-5 h-5 text-primary" />
            )}
            {exportingAll ? 'Exporting All...' : 'Export All'}
          </button>
          <button 
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 bg-white text-gray-900 border border-gray-200 px-6 py-4 rounded-2xl font-black text-sm shadow-sm hover:border-gray-300 hover:bg-gray-50 transition-all active:scale-95"
          >
            <Plus className="w-5 h-5 text-primary" />
            Create Custom Mix
          </button>
          <button 
            onClick={handleGenerate}
            disabled={generating}
            className="group relative flex items-center justify-center gap-2 bg-gray-900 text-white px-8 py-4 rounded-2xl font-black text-sm shadow-xl shadow-gray-900/20 hover:bg-black transition-all active:scale-95 disabled:opacity-50"
          >
            {generating ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Sparkles className="w-5 h-5 text-primary group-hover:rotate-12 transition-transform" />
            )}
            {generating ? 'Analyzing...' : 'Auto-Group Library'}
          </button>
        </div>
      </header>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {[1,2,3].map(i => (
            <div key={i} className="h-64 bg-white rounded-[32px] border border-gray-100 animate-pulse" />
          ))}
        </div>
      ) : playlists.length === 0 ? (
        <div className="bg-white rounded-[40px] border-2 border-dashed border-gray-100 p-20 text-center">
          <div className="w-20 h-20 bg-gray-50 rounded-3xl flex items-center justify-center mx-auto mb-6 text-gray-300">
            <Music2 className="w-10 h-10" />
          </div>
          <h3 className="text-xl font-black text-gray-900 mb-2">No playlists yet</h3>
          <p className="text-gray-500 max-w-sm mx-auto font-medium leading-relaxed">
            Create a custom mix or hit "Auto-Group" to let SongBus organize your tracks by genre and mood.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {playlists.map((pl) => (
            <div 
              key={pl.id} 
              onClick={() => viewTracks(pl)}
              className="cursor-pointer group bg-white rounded-[32px] border border-gray-100 shadow-xl shadow-gray-200/40 hover:shadow-gray-300/50 transition-all duration-300 flex flex-col p-8 overflow-hidden relative"
            >
              <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
                <Music2 className="w-32 h-32 -mr-8 -mt-8 rotate-12" />
              </div>
              
              <button 
                onClick={(e) => handleDelete(e, pl.id)}
                className="absolute top-4 right-4 p-2 bg-red-50 text-red-500 rounded-full opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-100"
                title="Delete Mix"
              >
                <Trash2 className="w-4 h-4" />
              </button>

              <div className="relative z-10 flex-1">
                <span className="text-[10px] font-black text-primary uppercase tracking-[0.2em] bg-primary/5 px-3 py-1 rounded-lg mb-4 inline-block">
                  {pl.source.replace('_', ' ')}
                </span>
                <h3 className="text-2xl font-black text-gray-900 leading-tight mb-2 truncate group-hover:text-primary transition-colors">
                  {pl.name}
                </h3>
                <p className="text-sm text-gray-400 font-bold uppercase tracking-wider flex items-center gap-1">
                  <ListMusic className="w-4 h-4" /> Tap to view tracks
                </p>
              </div>

              <div className="mt-10 flex items-center justify-between gap-4 relative z-10">
                {(() => {
                  const sync = parseExternalId(pl.external_id, pl.source);
                  const platforms = [];
                  if (sync.spotify) platforms.push('Spotify');
                  if (sync.ytmusic) platforms.push('YouTube Music');
                  if (platforms.length === 0) return <div />;
                  return (
                    <div className="flex flex-col gap-1 text-green-600">
                      <div className="flex items-center gap-1.5">
                        <CheckCircle2 className="w-4 h-4" />
                        <span className="text-[10px] font-black uppercase tracking-wider">Synced to:</span>
                      </div>
                      <span className="text-xs font-bold text-gray-500 pl-5 leading-none">
                        {platforms.join(' & ')}
                      </span>
                    </div>
                  );
                })()}
                
                <button
                  onClick={(e) => handleExportClick(e, pl)}
                  disabled={exportingId === pl.id}
                  className={`flex items-center gap-2 px-6 h-12 rounded-xl font-black text-xs uppercase tracking-widest transition-all ${
                    pl.external_id 
                    ? 'bg-gray-100 text-gray-700 hover:bg-gray-200' 
                    : 'bg-gray-900 text-white hover:bg-black shadow-lg shadow-gray-900/10'
                  } disabled:opacity-50`}
                >
                  {exportingId === pl.id ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                  {exportingId === pl.id ? 'Syncing...' : 'Export'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* View Tracks Modal */}
      {viewingPlaylist && (
        <div className="fixed inset-0 z-[150] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-950/80 backdrop-blur-md" onClick={() => setViewingPlaylist(null)} />
          <div className="relative bg-white w-full max-w-2xl max-h-[85vh] rounded-[40px] shadow-2xl flex flex-col animate-in fade-in zoom-in duration-200">
            <div className="px-8 py-6 border-b border-gray-50 flex items-center justify-between">
              <div>
                <h2 className="text-xl font-black text-gray-900">{viewingPlaylist.name}</h2>
                <p className="text-sm font-bold text-gray-400 uppercase tracking-widest mt-1">
                  {playlistTracks.length} Tracks
                </p>
              </div>
              <button onClick={() => setViewingPlaylist(null)} className="p-3 bg-gray-50 hover:bg-gray-100 rounded-full transition-all">
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-4 md:p-8">
              {loadingTracks ? (
                <div className="flex flex-col items-center justify-center py-20 text-gray-400">
                  <Loader2 className="w-8 h-8 animate-spin mb-4 text-primary" />
                  <p className="text-sm font-bold uppercase tracking-widest">Loading Tracks...</p>
                </div>
              ) : playlistTracks.length === 0 ? (
                <div className="text-center py-20">
                  <p className="text-sm font-bold text-gray-400 uppercase tracking-widest">Mix is empty</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {playlistTracks.map(t => (
                    <div key={t.id} className="flex items-center gap-4 bg-gray-50 p-4 rounded-[24px]">
                      <img src={t.thumbnail_url} className="w-16 h-16 rounded-2xl object-cover shadow-sm" alt="" />
                      <div className="flex-1 min-w-0">
                        <h4 className="text-base font-black text-gray-900 truncate">{t.title}</h4>
                        <p className="text-xs font-bold text-gray-500 uppercase tracking-wider truncate mt-1">{t.artist}</p>
                      </div>
                      <div className="hidden md:flex flex-col gap-1 items-end">
                        {t.genre && <span className="px-2 py-1 bg-purple-100 text-purple-700 text-[10px] font-bold rounded uppercase tracking-wider">{t.genre.split(',')[0]}</span>}
                        {t.mood && <span className="px-2 py-1 bg-blue-100 text-blue-700 text-[10px] font-bold rounded uppercase tracking-wider">{t.mood.split(',')[0]}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Create Custom Mix Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-[160] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-950/80 backdrop-blur-md" onClick={() => setShowCreateModal(false)} />
          <div className="relative bg-white w-full max-w-md rounded-[32px] shadow-2xl p-8 animate-in fade-in zoom-in duration-200">
            <h3 className="text-2xl font-black text-gray-900 mb-6">Create Custom Mix</h3>
            
            <div className="space-y-4 mb-8">
              <div>
                <label className="block text-xs font-black uppercase text-gray-500 tracking-widest mb-2">Mix Name</label>
                <input 
                  type="text" 
                  value={newMixName}
                  onChange={(e) => setNewMixName(e.target.value)}
                  placeholder="e.g. Late Night Drives"
                  className="w-full bg-gray-50 border border-gray-200 px-4 py-3 rounded-xl font-bold text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </div>
              <div>
                <label className="block text-xs font-black uppercase text-gray-500 tracking-widest mb-2">Genres (Optional)</label>
                <input 
                  type="text" 
                  value={newMixGenres}
                  onChange={(e) => setNewMixGenres(e.target.value)}
                  placeholder="e.g. pop, rock (comma separated)"
                  className="w-full bg-gray-50 border border-gray-200 px-4 py-3 rounded-xl font-bold text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </div>
              <div>
                <label className="block text-xs font-black uppercase text-gray-500 tracking-widest mb-2">Moods (Optional)</label>
                <input 
                  type="text" 
                  value={newMixMoods}
                  onChange={(e) => setNewMixMoods(e.target.value)}
                  placeholder="e.g. chill, workout (comma separated)"
                  className="w-full bg-gray-50 border border-gray-200 px-4 py-3 rounded-xl font-bold text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </div>
            </div>

            <div className="flex gap-3">
              <button onClick={() => setShowCreateModal(false)} className="flex-1 py-4 font-black text-sm text-gray-500 bg-gray-100 rounded-2xl hover:bg-gray-200 transition">Cancel</button>
              <button 
                onClick={handleCreateCustomMix}
                disabled={creatingMix || !newMixName}
                className="flex-[2] flex justify-center items-center py-4 font-black text-sm text-white bg-primary rounded-2xl hover:bg-primary/90 transition disabled:opacity-50 shadow-xl shadow-primary/20"
              >
                {creatingMix ? <Loader2 className="w-5 h-5 animate-spin" /> : 'Create Mix'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Export Platform Modal */}
      {exportingPlaylist && (
        <div className="fixed inset-0 z-[160] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-950/80 backdrop-blur-md" onClick={() => setExportingPlaylist(null)} />
          <div className="relative bg-white w-full max-w-md rounded-[32px] shadow-2xl p-8 animate-in fade-in zoom-in duration-200">
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-2xl font-black text-gray-900">Export Playlist</h3>
              <button onClick={() => setExportingPlaylist(null)} className="p-2 hover:bg-gray-100 rounded-full transition-all">
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            <p className="text-gray-500 font-medium text-sm mb-6 leading-relaxed">
              Choose the platform you want to export <strong className="text-gray-950">"{exportingPlaylist.name}"</strong> to.
            </p>
            
            <div className="flex flex-col gap-4 mb-6">
              <button 
                onClick={() => handleExport(exportingPlaylist.id, 'spotify')}
                className="flex items-center justify-between p-5 bg-green-50/30 hover:bg-green-50 border border-green-100 rounded-2xl transition-all duration-200 text-left group hover:border-green-200"
              >
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-green-500 text-white rounded-xl flex items-center justify-center font-bold text-lg">
                    S
                  </div>
                  <div>
                    <h4 className="font-black text-gray-900">Spotify</h4>
                    <p className="text-xs text-gray-500 font-medium mt-0.5">Export or sync to your Spotify account.</p>
                  </div>
                </div>
                <ChevronRight className="w-5 h-5 text-green-500 group-hover:translate-x-1 transition-transform" />
              </button>

              <button 
                onClick={() => handleExport(exportingPlaylist.id, 'ytmusic')}
                className="flex items-center justify-between p-5 bg-red-50/30 hover:bg-red-50 border border-red-100 rounded-2xl transition-all duration-200 text-left group hover:border-red-200"
              >
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-red-600 text-white rounded-xl flex items-center justify-center font-bold text-lg">
                    Y
                  </div>
                  <div>
                    <h4 className="font-black text-gray-900">YouTube Music</h4>
                    <p className="text-xs text-gray-500 font-medium mt-0.5">Export or sync to your YouTube Music account.</p>
                  </div>
                </div>
                <ChevronRight className="w-5 h-5 text-red-500 group-hover:translate-x-1 transition-transform" />
              </button>
            </div>
            
            <button 
              onClick={() => setExportingPlaylist(null)}
              className="w-full py-4 font-black text-sm text-gray-500 bg-gray-100 rounded-2xl hover:bg-gray-200 transition"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Export All Playlists Modal */}
      {showExportAllModal && (
        <div className="fixed inset-0 z-[160] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-950/80 backdrop-blur-md" onClick={() => setShowExportAllModal(false)} />
          <div className="relative bg-white w-full max-w-md rounded-[32px] shadow-2xl p-8 animate-in fade-in zoom-in duration-200">
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-2xl font-black text-gray-900">Export All Playlists</h3>
              <button onClick={() => setShowExportAllModal(false)} className="p-2 hover:bg-gray-100 rounded-full transition-all">
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            <p className="text-gray-500 font-medium text-sm mb-6 leading-relaxed">
              Export all of your AI generated and custom smart playlists in a single pass. Choose the platform to export to:
            </p>
            
            <div className="flex flex-col gap-4 mb-6">
              <button 
                onClick={() => handleExportAll('spotify')}
                className="flex items-center justify-between p-5 bg-green-50/30 hover:bg-green-50 border border-green-100 rounded-2xl transition-all duration-200 text-left group hover:border-green-200"
              >
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-green-500 text-white rounded-xl flex items-center justify-center font-bold text-lg">
                    S
                  </div>
                  <div>
                    <h4 className="font-black text-gray-900">Spotify</h4>
                    <p className="text-xs text-gray-500 font-medium mt-0.5">Export all playlists to Spotify.</p>
                  </div>
                </div>
                <ChevronRight className="w-5 h-5 text-green-500 group-hover:translate-x-1 transition-transform" />
              </button>

              <button 
                onClick={() => handleExportAll('ytmusic')}
                className="flex items-center justify-between p-5 bg-red-50/30 hover:bg-red-50 border border-red-100 rounded-2xl transition-all duration-200 text-left group hover:border-red-200"
              >
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-red-600 text-white rounded-xl flex items-center justify-center font-bold text-lg">
                    Y
                  </div>
                  <div>
                    <h4 className="font-black text-gray-900">YouTube Music</h4>
                    <p className="text-xs text-gray-500 font-medium mt-0.5">Export all playlists to YouTube Music.</p>
                  </div>
                </div>
                <ChevronRight className="w-5 h-5 text-red-500 group-hover:translate-x-1 transition-transform" />
              </button>
            </div>
            
            <button 
              onClick={() => setShowExportAllModal(false)}
              className="w-full py-4 font-black text-sm text-gray-500 bg-gray-100 rounded-2xl hover:bg-gray-200 transition"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Global Feedback Modal System */}
      {modal.show && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-950/60 backdrop-blur-sm" onClick={() => setModal({ ...modal, show: false })} />
          <div className="relative bg-white w-full max-w-sm sm:max-w-md rounded-[32px] shadow-2xl overflow-hidden p-8 animate-in fade-in zoom-in duration-200">
            <div className="flex flex-col items-center text-center">
              <div className={`w-20 h-20 rounded-full flex items-center justify-center mb-6 ${
                modal.type === 'error' ? 'bg-red-50 text-red-500' :
                modal.type === 'success' ? 'bg-green-50 text-green-500' :
                'bg-blue-50 text-primary'
              }`}>
                {modal.type === 'error' && <AlertCircle className="w-10 h-10" />}
                {modal.type === 'success' && <CheckCircle2 className="w-10 h-10" />}
                {modal.type === 'info' && <Info className="w-10 h-10" />}
              </div>
              <h3 className="text-2xl font-black text-gray-900 mb-2">{modal.title}</h3>
              <p className="text-sm text-gray-500 font-medium leading-relaxed mb-8">{modal.message}</p>
              
              <div className="flex flex-col gap-3 w-full">
                {modal.link && (
                  <a
                    href={modal.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`flex items-center justify-center gap-2 w-full px-6 h-14 rounded-2xl text-sm font-black text-white shadow-lg transition ${
                      modal.buttonClass || 'bg-green-500 shadow-green-500/20 hover:bg-green-600'
                    }`}
                  >
                    {modal.linkLabel || 'Open on Spotify'} <ExternalLink className="w-4 h-4" />
                  </a>
                )}
                <button
                  onClick={() => setModal({ ...modal, show: false })}
                  className="w-full px-6 h-14 rounded-2xl text-sm font-black bg-gray-900 text-white hover:bg-gray-800 transition"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
