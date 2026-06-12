import { useEffect, useState, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  ShieldAlert, Database, Trash2, CheckCircle2, 
  AlertCircle, Info, Disc3, Music2, RefreshCw,
  Sparkles, History
} from 'lucide-react';

type ModalConfig = {
  show: boolean;
  type: 'info' | 'success' | 'error' | 'confirm';
  title: string;
  message: string;
  onConfirm?: () => void;
  confirmText?: string;
};

export default function Settings() {
  const { token } = useAuth();
  const [status, setStatus] = useState({ spotify_connected: false, youtube_connected: false });
  const [loading, setLoading] = useState(false);
  const [browserAuth, setBrowserAuth] = useState('');
  const [savingBrowserAuth, setSavingBrowserAuth] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);
  const [enrichProgress, setEnrichProgress] = useState<{ message: string, progress: number, total: number, active: boolean } | null>(null);

  // Custom Modal State
  const [modal, setModal] = useState<ModalConfig>({
    show: false,
    type: 'info',
    title: '',
    message: ''
  });

  const fetchStatus = useCallback(() => {
    if (!token) return;
    fetch('/api/integrations/status', {
      headers: { Authorization: `Bearer ${token}` }
    })
    .then(res => res.json())
    .then(data => setStatus(data))
    .catch(console.error);
  }, [token]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const pollTask = useCallback(async (taskId: string) => {
    const poll = async () => {
      try {
        const res = await fetch(`/api/tasks/${taskId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (!res.ok) {
           setTaskRunning(false);
           return;
        }
        const task = await res.json();

        if (task.status === 'completed') {
          setModal({
            show: true,
            type: 'success',
            title: 'Job Complete',
            message: task.result?.message || 'The task finished successfully.'
          });
          setTaskRunning(false);
          return;
        }

        if (task.status === 'failed') {
          setModal({
            show: true,
            type: 'error',
            title: 'Job Failed',
            message: task.error || 'Something went wrong during the background process.'
          });
          setTaskRunning(false);
          return;
        }

        // Show live progress
        setModal({
          show: true,
          type: 'info',
          title: task.name + ' in Progress',
          message: task.message + (task.total ? ` (${task.progress} / ${task.total})` : '')
        });

        setTimeout(poll, 1500);
      } catch (err) {
        console.error('Polling error:', err);
        setTaskRunning(false);
      }
    };
    poll();
  }, [token]);

  const pollShadowTask = useCallback(async (taskId: string) => {
    const poll = async () => {
      try {
        const res = await fetch(`/api/tasks/${taskId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (!res.ok) {
           setEnrichProgress(null);
           setTaskRunning(false);
           return;
        }
        const task = await res.json();

        if (task.status === 'completed') {
          setEnrichProgress(null);
          setTaskRunning(false);
          setModal({
            show: true,
            type: 'success',
            title: 'Enrichment Complete',
            message: task.result?.message || 'Successfully enriched library.'
          });
          return;
        }

        if (task.status === 'failed') {
          setEnrichProgress(null);
          setTaskRunning(false);
          setModal({
            show: true,
            type: 'error',
            title: 'Enrichment Failed',
            message: task.error || 'Something went wrong.'
          });
          return;
        }

        setEnrichProgress({
           message: task.message,
           progress: task.progress,
           total: task.total,
           active: true
        });

        setTimeout(poll, 1500);
      } catch (err) {
        console.error('Polling error:', err);
        setEnrichProgress(null);
        setTaskRunning(false);
      }
    };
    poll();
  }, [token]);

  const handleEnrichLibrary = async () => {
    if (!token) return;
    setTaskRunning(true);
    setEnrichProgress({ message: 'Starting...', progress: 0, total: 100, active: true });

    try {
      const res = await fetch('/api/music/enrich-all', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.task_id) {
        pollShadowTask(data.task_id);
      } else {
        setTaskRunning(false);
        setEnrichProgress(null);
        setModal({ show: true, type: 'error', title: 'Failed to Start', message: data.detail || 'Could not start enrichment.' });
      }
    } catch (err: any) {
      setTaskRunning(false);
      setEnrichProgress(null);
      setModal({ show: true, type: 'error', title: 'Error', message: err.message });
    }
  };

  const handleSyncHistory = async () => {
    if (!token) return;
    setTaskRunning(true);
    setModal({ show: true, type: 'info', title: 'History Sync Started', message: 'Fetching your recently played tracks from connected accounts...' });

    try {
      const res = await fetch('/api/music/sync-history', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.task_id) {
        pollTask(data.task_id);
      } else {
        setTaskRunning(false);
        setModal({ show: true, type: 'error', title: 'Failed to Start', message: data.detail || 'Could not start sync.' });
      }
    } catch (err: any) {
      setTaskRunning(false);
      setModal({ show: true, type: 'error', title: 'Error', message: err.message });
    }
  };

  const handleSpotifyConnect = async () => {
    try {
      const res = await fetch('/api/integrations/spotify/auth-url', {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleYouTubeConnect = async () => {
    try {
      const res = await fetch('/api/integrations/youtube/auth-url', {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleDisconnect = (platform: 'spotify' | 'youtube') => {
    setModal({
      show: true,
      type: 'confirm',
      title: 'Disconnect Integration',
      message: `Are you sure you want to disconnect ${platform === 'spotify' ? 'Spotify' : 'YouTube Music'}? You will need to re-authenticate to sync your music.`,
      confirmText: 'Disconnect',
      onConfirm: () => executeDisconnect(platform)
    });
  };

  const executeDisconnect = async (platform: 'spotify' | 'youtube') => {
    setLoading(true);
    try {
      const res = await fetch(`/api/integrations/${platform}/disconnect`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        fetchStatus();
        setModal({ show: false, type: 'info', title: '', message: '' });
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveBrowserAuth = async () => {
    if (!token || !browserAuth.trim()) return;

    setSavingBrowserAuth(true);
    try {
      const res = await fetch('/api/integrations/youtube/browser-auth', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ headers_raw: browserAuth }),
      });
      const data = await res.json();
      if (res.ok) {
        setBrowserAuth('');
        setModal({
          show: true,
          type: 'success',
          title: 'Headers Saved',
          message: 'YouTube Music browser authentication has been updated successfully.'
        });
      } else {
        setModal({
          show: true,
          type: 'error',
          title: 'Save Failed',
          message: data.detail || 'Could not validate headers.'
        });
      }
    } catch (err) {
      console.error(err);
    } finally {
      setSavingBrowserAuth(false);
    }
  };

  const handleClearDatabase = () => {
    setModal({
      show: true,
      type: 'confirm',
      title: 'Wipe Library?',
      message: 'This will permanently delete all imported tracks, classification data, and playlist associations from your SongBus database. This action cannot be undone.',
      confirmText: 'Clear Everything',
      onConfirm: executeClearDatabase
    });
  };

  const executeClearDatabase = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/music/clear', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        setModal({
          show: true,
          type: 'success',
          title: 'Database Wiped',
          message: 'Your music library has been completely reset.'
        });
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto pb-20 animate-in fade-in duration-500">
      <header className="mb-10">
        <h1 className="text-3xl font-black text-gray-900 tracking-tight">Settings</h1>
        <p className="text-gray-500 font-medium">Manage your streaming integrations and library preferences.</p>
      </header>
      
      <div className="space-y-8">
        {/* Integrations Section */}
        <section className="bg-white rounded-[32px] border border-gray-100 shadow-xl shadow-gray-200/40 p-8 sm:p-10">
          <div className="flex items-center gap-4 mb-8">
            <div className="w-12 h-12 bg-blue-50 rounded-2xl flex items-center justify-center text-primary">
              <RefreshCw className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-black text-gray-900">Streaming Services</h2>
              <p className="text-sm text-gray-500 font-medium">Connect your accounts to sync music.</p>
            </div>
          </div>

          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 rounded-2xl bg-gray-50/50 border border-gray-100">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-green-500 rounded-xl flex items-center justify-center text-white shadow-lg shadow-green-500/20">
                  <Disc3 className="w-7 h-7" />
                </div>
                <div>
                  <h3 className="font-bold text-gray-900">Spotify</h3>
                  <p className="text-xs text-gray-400 font-bold uppercase tracking-wider">DNA & Export</p>
                </div>
              </div>
              {status.spotify_connected ? (
                <div className="flex items-center gap-4">
                  <span className="text-xs font-black text-green-600 bg-green-50 px-3 py-1.5 rounded-lg uppercase">Connected</span>
                  <button onClick={() => handleDisconnect('spotify')} className="text-sm font-bold text-red-400 hover:text-red-600 transition-colors">Disconnect</button>
                </div>
              ) : (
                <button onClick={handleSpotifyConnect} className="bg-green-500 hover:bg-green-600 text-white px-6 py-2.5 rounded-xl font-bold text-sm transition-all shadow-lg shadow-green-500/20">Connect</button>
              )}
            </div>

            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 rounded-2xl bg-gray-50/50 border border-gray-100">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-red-600 rounded-xl flex items-center justify-center text-white shadow-lg shadow-red-600/20">
                  <Music2 className="w-7 h-7" />
                </div>
                <div>
                  <h3 className="font-bold text-gray-900">YouTube Music</h3>
                  <p className="text-xs text-gray-400 font-bold uppercase tracking-wider">Import Hub</p>
                </div>
              </div>
              {status.youtube_connected ? (
                <div className="flex items-center gap-4">
                  <span className="text-xs font-black text-green-600 bg-green-50 px-3 py-1.5 rounded-lg uppercase">Connected</span>
                  <button onClick={() => handleDisconnect('youtube')} className="text-sm font-bold text-red-400 hover:text-red-600 transition-colors">Disconnect</button>
                </div>
              ) : (
                <button onClick={handleYouTubeConnect} className="bg-red-600 hover:bg-red-700 text-white px-6 py-2.5 rounded-xl font-bold text-sm transition-all shadow-lg shadow-red-600/20">Connect</button>
              )}
            </div>
          </div>
        </section>

        {/* Data Management Section */}
        <section className="bg-white rounded-[32px] border border-gray-100 shadow-xl shadow-gray-200/40 p-8 sm:p-10">
          <div className="flex items-center gap-4 mb-8">
            <div className="w-12 h-12 bg-purple-50 rounded-2xl flex items-center justify-center text-purple-600">
              <Sparkles className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-black text-gray-900">Data Management</h2>
              <p className="text-sm text-gray-500 font-medium">Supercharge your library with metadata.</p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <button 
              onClick={handleEnrichLibrary}
              disabled={taskRunning || enrichProgress?.active}
              className="flex items-center justify-center gap-3 p-6 rounded-2xl bg-gray-50 hover:bg-primary/5 border border-gray-100 group transition-all disabled:opacity-50 relative overflow-hidden text-left"
            >
              {enrichProgress?.active && enrichProgress.total > 0 && (
                <div 
                  className="absolute bottom-0 left-0 h-1 bg-primary transition-all duration-500" 
                  style={{ width: `${Math.min(100, (enrichProgress.progress / enrichProgress.total) * 100)}%` }} 
                />
              )}
              <div className="w-10 h-10 bg-white rounded-xl shadow-sm flex items-center justify-center text-primary group-hover:scale-110 transition-transform flex-shrink-0">
                {enrichProgress?.active ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />}
              </div>
              <div className="text-left w-full overflow-hidden">
                <p className="font-bold text-gray-900 truncate">{enrichProgress?.active ? 'Enriching Library...' : 'Enrich Library'}</p>
                <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest leading-none mt-1 truncate">
                  {enrichProgress?.active 
                    ? `${enrichProgress.progress} / ${enrichProgress.total} Tracks` 
                    : 'BPM, Energy & Lyrics'}
                </p>
              </div>
            </button>

            <button 
              onClick={handleSyncHistory}
              disabled={taskRunning}
              className="flex items-center justify-center gap-3 p-6 rounded-2xl bg-gray-50 hover:bg-blue-50 border border-gray-100 group transition-all disabled:opacity-50 text-left"
            >
              <div className="w-10 h-10 bg-white rounded-xl shadow-sm flex items-center justify-center text-blue-600 group-hover:scale-110 transition-transform">
                <History className="w-5 h-5" />
              </div>
              <div className="text-left">
                <p className="font-bold text-gray-900">Sync History</p>
                <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest leading-none mt-1">Fetch Recent Activity</p>
              </div>
            </button>
          </div>
        </section>

        {/* Browser Auth Section */}
        <section className="bg-white rounded-[32px] border border-gray-100 shadow-xl shadow-gray-200/40 p-8 sm:p-10">
          <div className="flex items-center gap-4 mb-6">
            <div className="w-12 h-12 bg-gray-900 rounded-2xl flex items-center justify-center text-white">
              <ShieldAlert className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-black text-gray-900">Advanced Authentication</h2>
              <p className="text-sm text-gray-500 font-medium">YouTube Music Browser Headers</p>
            </div>
          </div>
          
          <p className="text-sm text-gray-400 font-medium leading-relaxed mb-6">
            To access your private playlists and "Liked Music", paste the request headers from an authenticated YouTube Music session.
          </p>

          <textarea
            value={browserAuth}
            onChange={(e) => setBrowserAuth(e.target.value)}
            rows={6}
            className="w-full bg-gray-50 border-2 border-gray-100 rounded-2xl px-6 py-4 text-sm font-mono text-gray-600 focus:border-primary/30 focus:bg-white outline-none transition-all placeholder:text-gray-300"
            placeholder="Paste raw headers here..."
          />

          <button
            onClick={handleSaveBrowserAuth}
            disabled={savingBrowserAuth || !browserAuth.trim()}
            className="mt-4 w-full bg-gray-900 hover:bg-black text-white h-14 rounded-2xl font-black text-sm transition-all disabled:opacity-30"
          >
            {savingBrowserAuth ? 'Validating & Saving...' : 'Update Headers'}
          </button>
        </section>

        {/* Danger Zone */}
        <section className="bg-red-50/30 rounded-[32px] border-2 border-red-100/50 p-8 sm:p-10">
          <div className="flex items-center gap-4 mb-8">
            <div className="w-12 h-12 bg-red-100 rounded-2xl flex items-center justify-center text-red-600">
              <Database className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-black text-red-900">Danger Zone</h2>
              <p className="text-sm text-red-700/60 font-medium">Irreversible actions for your library.</p>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6 p-8 rounded-3xl bg-white border border-red-100 shadow-sm">
            <div className="flex-1">
              <h3 className="font-black text-gray-900 mb-1">Clear Music Database</h3>
              <p className="text-sm text-gray-500 font-medium leading-relaxed">
                Wipe all tracks and history. This will not affect your connected accounts.
              </p>
            </div>
            <button 
              onClick={handleClearDatabase}
              disabled={loading}
              className="flex items-center justify-center gap-2 bg-red-500 hover:bg-red-600 text-white px-8 h-14 rounded-2xl font-black text-sm transition-all shadow-xl shadow-red-500/20 disabled:opacity-50"
            >
              <Trash2 className="w-5 h-5" />
              Reset Library
            </button>
          </div>
        </section>
      </div>

      {/* Global Feedback Modal System */}
      {modal.show && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-950/60 backdrop-blur-sm" onClick={() => modal.type !== 'confirm' && setModal({ ...modal, show: false })} />
          <div className="relative bg-white w-full max-w-sm sm:max-w-md rounded-[32px] shadow-2xl overflow-hidden p-8 animate-in fade-in zoom-in duration-200">
            <div className="flex flex-col items-center text-center">
              <div className={`w-20 h-20 rounded-full flex items-center justify-center mb-6 ${
                modal.type === 'error' ? 'bg-red-50 text-red-500' :
                modal.type === 'success' ? 'bg-green-50 text-green-500' :
                modal.type === 'confirm' ? 'bg-orange-50 text-orange-500' :
                'bg-blue-50 text-primary'
              }`}>
                {modal.type === 'error' && <AlertCircle className="w-10 h-10" />}
                {modal.type === 'success' && <CheckCircle2 className="w-10 h-10" />}
                {modal.type === 'confirm' && <Trash2 className="w-10 h-10" />}
                {modal.type === 'info' && <Info className="w-10 h-10" />}
              </div>
              <h3 className="text-2xl font-black text-gray-900 mb-2">{modal.title}</h3>
              <p className="text-sm text-gray-500 font-medium leading-relaxed mb-8">{modal.message}</p>
              
              <div className="flex flex-col sm:flex-row items-stretch gap-3 w-full">
                {modal.type === 'confirm' ? (
                  <>
                    <button onClick={() => setModal({ ...modal, show: false })} className="order-2 sm:order-1 flex-1 px-6 h-14 rounded-2xl text-sm font-black text-gray-400 hover:bg-gray-50 transition">Cancel</button>
                    <button onClick={modal.onConfirm} className="order-1 sm:order-2 flex-1 px-6 h-14 rounded-2xl text-sm font-black bg-red-500 text-white shadow-lg shadow-red-500/20 hover:bg-red-600 transition">{modal.confirmText || 'Confirm'}</button>
                  </>
                ) : (
                  <button onClick={() => setModal({ ...modal, show: false })} className="w-full px-6 h-14 rounded-2xl text-sm font-black bg-gray-900 text-white hover:bg-gray-800 transition">Close</button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
