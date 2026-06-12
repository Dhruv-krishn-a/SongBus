import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  Sparkles, Loader2, Activity, Zap
} from 'lucide-react';

type Track = {
  id: number;
  title: string;
  artist: string;
  thumbnail_url?: string;
  genre?: string;
  mood?: string;
  bpm?: number;
  energy?: number;
};

export default function SmartPlaylists() {
  const { token } = useAuth();
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [message, setMessage] = useState('');

  const handleGenerate = async () => {
    if (!token || !prompt.trim()) return;
    
    setLoading(true);
    setTracks([]);
    setMessage('');

    try {
      const res = await fetch('/api/music/ai-generate', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}` 
        },
        body: JSON.stringify({ prompt })
      });
      const data = await res.json();
      if (res.ok) {
        setTracks(data.tracks || []);
        setMessage(data.message || 'Mix generated!');
      } else {
        setMessage(data.detail || 'Failed to generate playlist.');
      }
    } catch (err: any) {
      setMessage(err.message || 'An error occurred.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-1 sm:px-2 md:px-0 space-y-8 animate-in fade-in duration-500 pb-20">
      <header className="text-center lg:text-left mb-10">
        <h1 className="text-3xl md:text-5xl font-black text-gray-900 tracking-tight flex items-center justify-center lg:justify-start gap-4">
          <Sparkles className="w-10 h-10 text-primary" />
          AI DJ
        </h1>
        <p className="text-gray-500 font-medium mt-2 text-lg">Tell Gemini what you want to hear, and it will build the perfect mix from your library's deep DNA.</p>
      </header>

      {/* Input Area */}
      <div className="bg-white rounded-[32px] border border-gray-100 shadow-2xl shadow-primary/5 p-4 sm:p-6 flex flex-col md:flex-row gap-4 relative overflow-hidden group focus-within:border-primary/30 transition-all">
        <textarea 
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g., 'Make me a high energy workout mix around 120 BPM from my Pop songs'"
          className="flex-1 resize-none h-24 md:h-auto bg-transparent border-none outline-none text-gray-700 font-medium text-lg placeholder:text-gray-300 p-2"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleGenerate();
            }
          }}
        />
        <button 
          onClick={handleGenerate}
          disabled={loading || !prompt.trim()}
          className="h-14 md:h-auto md:w-32 bg-gray-900 text-white rounded-2xl font-black shadow-xl hover:bg-gray-800 transition-all disabled:opacity-50 flex items-center justify-center"
        >
          {loading ? <Loader2 className="w-6 h-6 animate-spin" /> : 'Generate'}
        </button>
      </div>

      {/* Results */}
      {message && (
        <div className="text-center py-4">
          <p className="font-bold text-gray-500">{message}</p>
        </div>
      )}

      {tracks.length > 0 && (
        <div className="bg-white rounded-[32px] border border-gray-100 shadow-xl shadow-gray-200/40 overflow-hidden animate-in slide-in-from-bottom-8 duration-700">
          <div className="p-6 bg-gray-50 border-b border-gray-100 flex items-center justify-between sticky top-0 z-10 backdrop-blur-xl bg-gray-50/80">
            <h3 className="text-xl font-black text-gray-900">Your Custom Mix</h3>
            <button className="px-6 py-3 bg-primary text-white text-sm font-black rounded-xl hover:bg-blue-600 transition shadow-lg shadow-primary/20">
              Save to Platform
            </button>
          </div>
          <div className="divide-y divide-gray-50">
            {tracks.map((t, idx) => (
              <div key={t.id} className="flex items-center gap-4 p-4 hover:bg-primary/[0.02] transition-colors group">
                <div className="w-8 text-center text-sm font-bold text-gray-300 group-hover:text-primary transition-colors">{idx + 1}</div>
                <div className="w-12 h-12 rounded-xl bg-gray-100 overflow-hidden shadow-sm flex-shrink-0">
                  {t.thumbnail_url && <img src={t.thumbnail_url} className="w-full h-full object-cover" alt="" />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-black text-gray-900 truncate">{t.title}</p>
                  <p className="text-xs font-bold text-gray-400 truncate">{t.artist}</p>
                </div>
                <div className="hidden md:flex items-center gap-6 px-4">
                  <div className="flex items-center gap-2">
                    <Activity className="w-4 h-4 text-gray-300" />
                    <span className="text-sm font-bold text-gray-500 w-12">{t.bpm ? Math.round(t.bpm) : '--'}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Zap className="w-4 h-4 text-gray-300" />
                    <span className="text-sm font-bold text-gray-500 w-12">{t.energy ? `${Math.round(t.energy * 100)}%` : '--'}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
