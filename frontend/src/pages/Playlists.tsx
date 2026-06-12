import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  Sparkles, Send, CheckCircle2, AlertCircle, 
  ExternalLink, Loader2, Music2, Info
} from 'lucide-react';

type ModalConfig = {
  show: boolean;
  type: 'info' | 'success' | 'error';
  title: string;
  message: string;
  link?: string;
};

interface PlaylistData {
  id: number;
  name: string;
  source: string;
  external_id?: string;
}

export default function Playlists() {
  const { token } = useAuth();
  const [playlists, setPlaylists] = useState<PlaylistData[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [exportingId, setExportingId] = useState<number | null>(null);

  // UI Modal state
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

  const handleExport = async (id: number) => {
    if (!token) return;
    setExportingId(id);
    try {
      const res = await fetch(`/api/music/export-spotify/${id}`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        setModal({
          show: true,
          type: 'success',
          title: 'Synced to Spotify',
          message: `Matched ${data.matched} out of ${data.total} tracks. Your playlist is now live on your Spotify account!`,
          link: data.playlist_url
        });
        fetchPlaylists();
      } else {
        setModal({
          show: true,
          type: 'error',
          title: 'Export Failed',
          message: data.detail || 'Visit Settings to connect Spotify.'
        });
      }
    } catch (err) {
      console.error(err);
    } finally {
      setExportingId(null);
    }
  };

  return (
    <div className="max-w-7xl mx-auto animate-in fade-in duration-500">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
        <div>
          <h1 className="text-3xl font-black text-gray-900 tracking-tight">Smart Playlists</h1>
          <p className="text-gray-500 font-medium mt-1">AI-powered grouping of your music library.</p>
        </div>
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
          {generating ? 'Analyzing Library...' : 'Generate Smart Mixes'}
        </button>
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
            Import some tracks in the Library tab and hit "Generate" to let SongBus organize them by genre and mood.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {playlists.map((pl) => (
            <div key={pl.id} className="group bg-white rounded-[32px] border border-gray-100 shadow-xl shadow-gray-200/40 hover:shadow-gray-300/50 transition-all duration-300 flex flex-col p-8 overflow-hidden relative">
              <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
                <Music2 className="w-32 h-32 -mr-8 -mt-8 rotate-12" />
              </div>

              <div className="relative z-10 flex-1">
                <span className="text-[10px] font-black text-primary uppercase tracking-[0.2em] bg-primary/5 px-3 py-1 rounded-lg mb-4 inline-block">
                  {pl.source.replace('_', ' ')}
                </span>
                <h3 className="text-2xl font-black text-gray-900 leading-tight mb-2 truncate group-hover:text-primary transition-colors">
                  {pl.name}
                </h3>
                <p className="text-sm text-gray-400 font-bold uppercase tracking-wider">
                  Automated Mix
                </p>
              </div>

              <div className="mt-10 flex items-center justify-between gap-4 relative z-10">
                {pl.external_id ? (
                  <div className="flex items-center gap-2 text-green-600">
                    <CheckCircle2 className="w-5 h-5" />
                    <span className="text-xs font-black uppercase tracking-widest">Synced</span>
                  </div>
                ) : (
                  <div />
                )}
                
                <button
                  onClick={() => handleExport(pl.id)}
                  disabled={exportingId === pl.id}
                  className={`flex items-center gap-2 px-6 h-12 rounded-xl font-black text-xs uppercase tracking-widest transition-all ${
                    pl.external_id 
                    ? 'bg-green-50 text-green-600 hover:bg-green-100' 
                    : 'bg-gray-900 text-white hover:bg-black shadow-lg shadow-gray-900/10'
                  } disabled:opacity-50`}
                >
                  {exportingId === pl.id ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                  {exportingId === pl.id ? 'Syncing...' : pl.external_id ? 'Update Spotify' : 'Export'}
                </button>
              </div>
            </div>
          ))}
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
                    className="flex items-center justify-center gap-2 w-full px-6 h-14 rounded-2xl text-sm font-black bg-green-500 text-white shadow-lg shadow-green-500/20 hover:bg-green-600 transition"
                  >
                    Open on Spotify <ExternalLink className="w-4 h-4" />
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
