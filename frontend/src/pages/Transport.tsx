import { useEffect, useState, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  ArrowRightLeft, Music2, Globe, AlertCircle, CheckCircle2, 
  Loader2, RefreshCw, Info
} from 'lucide-react';

type AuditTrack = {
  id: number;
  title: string;
  artist: string;
  thumbnail_url?: string;
};

type AuditResponse = {
  ready: AuditTrack[];
  missing: AuditTrack[];
  total_source: number;
};

type ModalConfig = {
  show: boolean;
  type: 'info' | 'success' | 'error';
  title: string;
  message: string;
};

export default function Transport() {
  const { token } = useAuth();
  const [source, setSource] = useState<'youtube' | 'spotify'>('youtube');
  const [destination, setDestination] = useState<'youtube' | 'spotify'>('spotify');
  
  const [loading, setLoading] = useState(false);
  const [auditData, setAuditData] = useState<AuditResponse | null>(null);
  
  const [playlistName, setPlaylistName] = useState('SongBus Transport Mix');
  const [exporting, setExporting] = useState(false);
  
  const [modal, setModal] = useState<ModalConfig>({ show: false, type: 'info', title: '', message: '' });

  const handleAudit = async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/transport/audit?source=${source}&destination=${destination}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        setAuditData(data);
      } else {
        throw new Error(data.detail || 'Audit failed');
      }
    } catch (err: any) {
      setModal({ show: true, type: 'error', title: 'Audit Error', message: err.message });
    } finally {
      setLoading(false);
    }
  };

  const handleSwap = () => {
    setSource(destination);
    setDestination(source);
    setAuditData(null);
  };

  useEffect(() => {
    setAuditData(null);
  }, [source, destination]);

  const pollTask = useCallback(async (taskId: string) => {
    const poll = async () => {
      try {
        const res = await fetch(`/api/tasks/${taskId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (!res.ok) {
           setExporting(false);
           return;
        }
        const task = await res.json();

        if (task.status === 'completed') {
          setModal({
            show: true,
            type: 'success',
            title: 'Export Complete',
            message: task.result?.message || 'Successfully exported tracks.'
          });
          setExporting(false);
          return;
        }

        if (task.status === 'failed') {
          setModal({
            show: true,
            type: 'error',
            title: 'Export Failed',
            message: task.error || 'Something went wrong.'
          });
          setExporting(false);
          return;
        }

        setModal({
          show: true,
          type: 'info',
          title: task.name + ' in Progress',
          message: task.message + (task.total ? ` (${task.progress} / ${task.total})` : '')
        });

        setTimeout(poll, 3000);
      } catch (err) {
        console.error('Polling error:', err);
        setExporting(false);
      }
    };
    poll();
  }, [token]);

  const handleExport = async () => {
    if (!token || !auditData || auditData.ready.length === 0) return;
    if (!playlistName.trim()) {
       setModal({ show: true, type: 'error', title: 'Invalid Name', message: 'Please provide a playlist name.' });
       return;
    }

    setExporting(true);
    setModal({ show: true, type: 'info', title: 'Starting Export', message: 'Queueing export job...' });

    try {
      const trackIds = auditData.ready.map(t => t.id);
      const res = await fetch('/api/transport/export', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}` 
        },
        body: JSON.stringify({
          track_ids: trackIds,
          destination: destination,
          playlist_name: playlistName
        })
      });
      const data = await res.json();
      if (res.ok && data.task_id) {
        pollTask(data.task_id);
      } else {
        throw new Error(data.detail || 'Export failed');
      }
    } catch (err: any) {
      setExporting(false);
      setModal({ show: true, type: 'error', title: 'Export Error', message: err.message });
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-1 sm:px-2 md:px-0 space-y-8 animate-in fade-in duration-500 pb-20">
      <header className="text-center lg:text-left">
        <h1 className="text-3xl md:text-4xl font-black text-gray-900 tracking-tight">Transport Hub</h1>
        <p className="text-gray-500 font-medium mt-2">Seamlessly sync your music across platforms using database intelligence.</p>
      </header>

      {/* Control Panel */}
      <div className="bg-white rounded-[32px] border border-gray-100 shadow-xl shadow-gray-200/40 p-6 sm:p-10 flex flex-col md:flex-row items-center justify-between gap-8">
        
        <div className="flex items-center w-full md:w-auto gap-4">
           <div className={`flex-1 flex flex-col items-center justify-center p-6 rounded-2xl border-2 transition-all ${source === 'youtube' ? 'border-red-500 bg-red-50 text-red-600' : 'border-green-500 bg-green-50 text-green-600'}`}>
              <span className="text-[10px] font-black uppercase tracking-widest opacity-60 mb-2">Source</span>
              {source === 'youtube' ? <Music2 className="w-8 h-8 mb-2" /> : <Globe className="w-8 h-8 mb-2" />}
              <span className="font-bold">{source === 'youtube' ? 'YouTube Music' : 'Spotify'}</span>
           </div>

           <button onClick={handleSwap} className="p-4 bg-gray-50 hover:bg-gray-100 rounded-full text-gray-400 hover:text-primary transition-all active:scale-90">
             <ArrowRightLeft className="w-6 h-6" />
           </button>

           <div className={`flex-1 flex flex-col items-center justify-center p-6 rounded-2xl border-2 transition-all ${destination === 'spotify' ? 'border-green-500 bg-green-50 text-green-600' : 'border-red-500 bg-red-50 text-red-600'}`}>
              <span className="text-[10px] font-black uppercase tracking-widest opacity-60 mb-2">Destination</span>
              {destination === 'spotify' ? <Globe className="w-8 h-8 mb-2" /> : <Music2 className="w-8 h-8 mb-2" />}
              <span className="font-bold">{destination === 'spotify' ? 'Spotify' : 'YouTube Music'}</span>
           </div>
        </div>

        <div className="flex flex-col items-center md:items-end w-full md:w-auto gap-4">
           <button 
             onClick={handleAudit}
             disabled={loading}
             className="w-full md:w-auto px-10 h-14 bg-gray-900 text-white rounded-2xl font-black shadow-xl hover:bg-gray-800 transition-all flex items-center justify-center gap-2"
           >
             {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <RefreshCw className="w-5 h-5" />}
             Run Audit
           </button>
           <p className="text-xs font-bold text-gray-400 text-center md:text-right">
             Audits instantly against local database. <br/> Doesn't use API limits.
           </p>
        </div>
      </div>

      {/* Audit Results */}
      {auditData && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 animate-in slide-in-from-bottom-4 duration-500">
          
          {/* Ready to Transfer */}
          <div className="bg-white rounded-[32px] border border-green-100 shadow-xl shadow-green-500/10 overflow-hidden flex flex-col h-[600px]">
             <div className="p-6 bg-green-50 border-b border-green-100 flex items-center justify-between">
                <div>
                  <h3 className="text-lg font-black text-green-900 flex items-center gap-2"><CheckCircle2 className="w-5 h-5" /> Ready to Transfer</h3>
                  <p className="text-sm font-bold text-green-700/60 mt-1">{auditData.ready.length} perfect matches found.</p>
                </div>
                <div className="text-3xl font-black text-green-600 opacity-20">{Math.round((auditData.ready.length / (auditData.total_source || 1)) * 100)}%</div>
             </div>
             <div className="flex-1 overflow-y-auto p-4 space-y-2">
                {auditData.ready.map(t => (
                  <div key={t.id} className="flex items-center gap-4 p-3 hover:bg-gray-50 rounded-xl transition-colors">
                     <img src={t.thumbnail_url} className="w-12 h-12 rounded-lg object-cover bg-gray-100" alt=""/>
                     <div className="min-w-0">
                       <p className="font-bold text-gray-900 truncate">{t.title}</p>
                       <p className="text-xs text-gray-500 truncate">{t.artist}</p>
                     </div>
                  </div>
                ))}
                {auditData.ready.length === 0 && (
                  <div className="h-full flex flex-col items-center justify-center text-gray-400">
                     <AlertCircle className="w-12 h-12 mb-4 opacity-20" />
                     <p className="font-bold">No matches found.</p>
                     <p className="text-sm mt-2">Try running the Enrichment job first.</p>
                  </div>
                )}
             </div>
             {auditData.ready.length > 0 && (
               <div className="p-6 bg-white border-t border-gray-100 space-y-4">
                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-black uppercase text-gray-400 tracking-widest">Playlist Name</label>
                    <input 
                      type="text" 
                      value={playlistName}
                      onChange={(e) => setPlaylistName(e.target.value)}
                      className="w-full bg-gray-50 border-2 border-gray-100 rounded-xl px-4 py-3 text-sm font-bold focus:border-primary/50 outline-none"
                    />
                  </div>
                  <button 
                    onClick={handleExport}
                    disabled={exporting}
                    className="w-full h-14 bg-primary text-white rounded-xl font-black shadow-lg shadow-primary/30 hover:bg-blue-600 transition-all flex items-center justify-center"
                  >
                    {exporting ? <Loader2 className="w-5 h-5 animate-spin" /> : 'Export Playlist Now'}
                  </button>
               </div>
             )}
          </div>

          {/* Missing / Action Required */}
          <div className="bg-white rounded-[32px] border border-gray-100 shadow-xl shadow-gray-200/40 overflow-hidden flex flex-col h-[600px]">
             <div className="p-6 bg-gray-50 border-b border-gray-100 flex items-center justify-between">
                <div>
                  <h3 className="text-lg font-black text-gray-900 flex items-center gap-2"><AlertCircle className="w-5 h-5 text-orange-500" /> Missing Matches</h3>
                  <p className="text-sm font-bold text-gray-500 mt-1">{auditData.missing.length} tracks need attention.</p>
                </div>
             </div>
             <div className="flex-1 overflow-y-auto p-4 space-y-2">
                {auditData.missing.map(t => (
                  <div key={t.id} className="flex items-center gap-4 p-3 hover:bg-gray-50 rounded-xl transition-colors opacity-60 hover:opacity-100 grayscale hover:grayscale-0">
                     <div className="w-12 h-12 rounded-lg bg-gray-200 overflow-hidden">
                       {t.thumbnail_url && <img src={t.thumbnail_url} className="w-full h-full object-cover" alt=""/>}
                     </div>
                     <div className="min-w-0">
                       <p className="font-bold text-gray-900 truncate">{t.title}</p>
                       <p className="text-xs text-gray-500 truncate">{t.artist}</p>
                     </div>
                  </div>
                ))}
                {auditData.missing.length === 0 && (
                  <div className="h-full flex flex-col items-center justify-center text-green-500/50">
                     <CheckCircle2 className="w-12 h-12 mb-4" />
                     <p className="font-bold text-green-700">All tracks matched!</p>
                  </div>
                )}
             </div>
          </div>

        </div>
      )}

      {/* Modals */}
      {modal.show && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-950/60 backdrop-blur-sm" onClick={() => setModal({ ...modal, show: false })} />
          <div className="relative bg-white w-full max-w-sm rounded-[32px] shadow-2xl p-8 animate-in fade-in zoom-in duration-200">
            <div className="flex flex-col items-center text-center">
              <div className={`w-20 h-20 rounded-full flex items-center justify-center mb-6 ${modal.type === 'error' ? 'bg-red-50 text-red-500' : modal.type === 'success' ? 'bg-green-50 text-green-500' : 'bg-blue-50 text-primary'}`}>
                {modal.type === 'error' && <AlertCircle className="w-10 h-10" />}
                {modal.type === 'success' && <CheckCircle2 className="w-10 h-10" />}
                {modal.type === 'info' && <Info className="w-10 h-10" />}
              </div>
              <h3 className="text-2xl font-black text-gray-900 mb-2">{modal.title}</h3>
              <p className="text-sm text-gray-500 font-medium mb-8 leading-relaxed">{modal.message}</p>
              <button onClick={() => setModal({ ...modal, show: false })} className="w-full px-6 h-14 rounded-2xl text-sm font-black bg-gray-900 text-white">Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
