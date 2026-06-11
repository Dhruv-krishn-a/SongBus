import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  Music, Mic2, Disc,  
  TrendingUp, Sparkles, Brain, Compass, 
  Layers, Gauge, Loader2
} from 'lucide-react';

const Dashboard = () => {
  const [insights, setInsights] = useState<any>(null);
  const [aiInsights, setAiInsights] = useState<any>(() => {
    const saved = localStorage.getItem('ai_insights');
    return saved ? JSON.parse(saved) : null;
  });
  const [loadingAi, setLoadingAi] = useState(false);
  const { token } = useAuth();

  useEffect(() => {
    if (!token) return;

    // Fetch Basic Insights
    fetch('/api/music/insights', {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(res => res.json())
    .then(data => setInsights(data))
    .catch(console.error);
  }, [token]);

  const handleAnalyze = () => {
    if (!token) return;
    
    setLoadingAi(true);
    fetch('/api/music/insights/ai', {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(async res => {
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || 'Analysis failed');
      setAiInsights(data);
      localStorage.setItem('ai_insights', JSON.stringify(data));
    })
    .catch(err => {
      console.error(err);
      alert(err.message);
    })
    .finally(() => setLoadingAi(false));
  };

  const stats = [
    { 
      name: 'Total Tracks', 
      value: insights?.total_tracks || 0, 
      icon: Music, 
      gradient: 'from-blue-600 to-blue-400'
    },
    { 
      name: 'Top Artist', 
      value: insights?.top_artist || 'Scanning...', 
      icon: Mic2, 
      gradient: 'from-purple-600 to-purple-400'
    },
    { 
      name: 'Top Genre', 
      value: insights?.top_genre || 'Scanning...', 
      icon: Disc, 
      gradient: 'from-pink-600 to-pink-400'
    },
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500 pb-20">
      {/* Hero Section */}
      <section className="relative overflow-hidden rounded-[40px] bg-gray-900 px-8 py-16 shadow-2xl shadow-blue-900/10">
        <div className="absolute top-0 right-0 -mt-20 -mr-20 w-96 h-96 bg-primary/20 rounded-full blur-[100px]" />
        <div className="absolute bottom-0 left-0 -mb-20 -ml-20 w-64 h-64 bg-secondary/20 rounded-full blur-[80px]" />
        
        <div className="relative z-10 flex flex-col items-center text-center">
          <div className="bg-primary/10 border border-primary/20 px-4 py-2 rounded-full mb-6 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-primary" />
            <span className="text-[11px] font-black text-primary uppercase tracking-[0.2em]">Powered by Gemini AI</span>
          </div>
          <h1 className="text-4xl md:text-6xl font-black text-white leading-tight mb-6 tracking-tight">
            Analyze your music <br/>
            <span className="bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent">
              Intelligence in motion.
            </span>
          </h1>
          <p className="text-gray-400 max-w-2xl text-lg font-medium leading-relaxed mb-10">
            SongBus has scanned your YouTube library. We've identified {insights?.total_tracks || 0} unique footprints.
            Below is your personalized AI deep dive.
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            <button 
              onClick={handleAnalyze}
              disabled={loadingAi}
              className="bg-white text-gray-900 px-10 py-4 rounded-[20px] font-black text-sm shadow-xl hover:bg-gray-100 transition-all active:scale-95 disabled:opacity-50 flex items-center gap-2"
            >
              {loadingAi ? <Loader2 className="w-4 h-4 animate-spin" /> : <Brain className="w-4 h-4" />}
              {loadingAi ? 'Analyzing...' : 'Analyze Library'}
            </button>
            <button className="bg-white/10 text-white backdrop-blur-md px-10 py-4 rounded-[20px] font-black text-sm border border-white/10 hover:bg-white/20 transition-all">
              Manage Collection
            </button>
          </div>
        </div>
      </section>

      {/* AI Deep Analysis Section */}
      <section className="space-y-6">
        <div className="flex items-center gap-2 px-2">
          <Brain className="w-6 h-6 text-primary" />
          <h3 className="text-2xl font-black text-gray-900 tracking-tight">AI Deep Analysis</h3>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Personality Card */}
          <div className="lg:col-span-2 bg-white rounded-[32px] border border-gray-100 shadow-xl shadow-gray-200/40 p-10 relative overflow-hidden group">
            <div className="absolute top-0 right-0 p-8 opacity-[0.03] group-hover:opacity-[0.08] transition-opacity">
              <Sparkles className="w-48 h-48 rotate-12" />
            </div>
            
            <div className="relative z-10 space-y-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-primary/10 rounded-xl flex items-center justify-center text-primary">
                  <Compass className="w-6 h-6" />
                </div>
                <span className="text-xs font-black text-gray-400 uppercase tracking-widest">Music Personality</span>
              </div>
              
              {loadingAi ? (
                <div className="space-y-3 animate-pulse">
                  <div className="h-6 bg-gray-100 rounded w-3/4" />
                  <div className="h-6 bg-gray-100 rounded w-1/2" />
                </div>
              ) : aiInsights?.personality ? (
                <p className="text-2xl font-bold text-gray-900 leading-snug">
                  {aiInsights.personality}
                </p>
              ) : (
                <p className="text-gray-400 italic">No analysis yet. Click 'Sync' to generate.</p>
              )}

              <div className="pt-8 border-t border-gray-50 grid grid-cols-1 md:grid-cols-3 gap-6">
                {aiInsights?.themes?.map((theme: string, i: number) => (
                  <div key={i} className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-primary" />
                    <span className="text-xs font-black text-gray-500 uppercase tracking-wider">{theme}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Vibe Score Card */}
          <div className="bg-gradient-to-br from-gray-900 to-gray-800 rounded-[32px] p-10 text-white shadow-2xl relative overflow-hidden">
            <div className="absolute top-0 right-0 -mt-10 -mr-10 w-40 h-40 bg-primary/10 rounded-full blur-3xl" />
            
            <div className="flex flex-col items-center justify-center h-full space-y-6 text-center">
              <div className="relative">
                <Gauge className="w-24 h-24 text-primary opacity-20" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-5xl font-black">{aiInsights?.vibe_score || '--'}</span>
                </div>
              </div>
              <div>
                <h4 className="text-lg font-black tracking-tight">Vibe Check</h4>
                <p className="text-sm text-gray-400 font-medium mt-1">Consistency of your taste profile.</p>
              </div>
              <div className="w-full bg-white/10 h-2 rounded-full overflow-hidden">
                <div 
                  className="bg-primary h-full transition-all duration-1000" 
                  style={{ width: `${aiInsights?.vibe_score || 0}%` }} 
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Stats & Trends */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {stats.map((item) => (
          <div key={item.name} className="group bg-white p-8 rounded-[32px] border border-gray-100 shadow-lg hover:shadow-xl transition-all duration-300">
            <div className="flex items-center justify-between mb-6">
              <div className={`w-14 h-14 rounded-2xl bg-gradient-to-br ${item.gradient} flex items-center justify-center shadow-lg`}>
                <item.icon className="w-7 h-7 text-white" />
              </div>
              <TrendingUp className="w-5 h-5 text-green-500 opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
            <p className="text-[11px] font-black text-gray-400 uppercase tracking-[0.2em]">{item.name}</p>
            <h4 className="text-2xl font-black text-gray-900 mt-2 truncate leading-tight">{item.value}</h4>
          </div>
        ))}
      </section>

      {/* Bottom Insights */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Recommendation Card */}
        <div className="bg-primary rounded-[32px] p-10 text-white shadow-2xl shadow-primary/20 flex flex-col justify-between">
          <div>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 bg-white/20 rounded-xl flex items-center justify-center">
                <Compass className="w-6 h-6" />
              </div>
              <span className="text-xs font-black uppercase tracking-widest text-white/60">AI Recommendation</span>
            </div>
            <h3 className="text-3xl font-black leading-tight mb-4">What's Next?</h3>
            <p className="text-primary-foreground/80 font-medium leading-relaxed mb-10">
              {aiInsights?.recommendation || "Our AI is busy analyzing your deeper frequencies. Check back in a moment."}
            </p>
          </div>
          <button className="w-full bg-white text-primary h-14 rounded-2xl font-black text-sm hover:shadow-xl transition-all active:scale-95">
            Explore on YouTube
          </button>
        </div>

        {/* Recent Library Activity */}
        <div className="bg-white rounded-[32px] p-10 border border-gray-100 shadow-xl shadow-gray-200/40">
          <div className="flex items-center justify-between mb-8">
            <h3 className="text-xl font-black text-gray-900 flex items-center gap-3">
              <Layers className="w-6 h-6 text-gray-400" />
              Genre Footprint
            </h3>
          </div>
          
          <div className="space-y-6">
            {insights?.genre_distribution ? (
              Object.entries(insights.genre_distribution).slice(0, 4).map(([genre, count]: any) => (
                <div key={genre} className="space-y-2">
                  <div className="flex justify-between text-xs font-black uppercase tracking-widest">
                    <span className="text-gray-900">{genre}</span>
                    <span className="text-gray-400">{count} Songs</span>
                  </div>
                  <div className="w-full bg-gray-50 h-2 rounded-full overflow-hidden">
                    <div 
                      className="bg-primary h-full" 
                      style={{ width: `${(count / (insights.total_tracks || 1)) * 100}%` }} 
                    />
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-10">
                <Loader2 className="w-10 h-10 animate-spin text-gray-100 mx-auto" />
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
};

export default Dashboard;
