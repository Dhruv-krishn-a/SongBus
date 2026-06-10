import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Library from './pages/Library';
import Login from './pages/Login';
import Settings from './pages/Settings';
import SpotifyCallback from './pages/SpotifyCallback';
import YouTubeCallback from './pages/YouTubeCallback';
import Playlists from './pages/Playlists';
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/callback" element={<SpotifyCallback />} />
          <Route path="/callback/youtube" element={<YouTubeCallback />} />
          
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<Layout />}>
              <Route index element={<Dashboard />} />
              <Route path="library" element={<Library />} />
              <Route path="playlists" element={<Playlists />} />
              <Route path="settings" element={<Settings />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
