import { useState } from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import { Home, Library, ListMusic, Settings, LogOut, Menu, X, ArrowRightLeft, Sparkles } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Logo from './Logo';

const Layout = () => {
  const location = useLocation();
  const { logout } = useAuth();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  const navigation = [
    { name: 'Dashboard', href: '/', icon: Home },
    { name: 'Library', href: '/library', icon: Library },
    { name: 'Transport Hub', href: '/transport', icon: ArrowRightLeft },
    { name: 'Smart Mixes', href: '/playlists', icon: ListMusic },
    { name: 'AI DJ', href: '/ai-dj', icon: Sparkles },
    { name: 'Settings', href: '/settings', icon: Settings },
  ];

  const closeMobileMenu = () => setIsMobileMenuOpen(false);

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden font-sans">
      {/* Sidebar - Desktop */}
      <aside className="hidden lg:flex flex-col w-72 bg-white border-r border-gray-200 shadow-sm z-20">
        <div className="flex items-center gap-3 px-8 h-20 border-b border-gray-50">
          <Logo className="w-10 h-10" />
          <h1 className="text-xl font-bold bg-gradient-to-r from-gray-900 to-gray-600 bg-clip-text text-transparent">
            SongBus
          </h1>
        </div>

        <nav className="flex-1 px-4 py-6 space-y-1">
          {navigation.map((item) => {
            const isActive = location.pathname === item.href;
            return (
              <Link
                key={item.name}
                to={item.href}
                className={`group flex items-center px-4 py-3 text-sm font-semibold rounded-2xl transition-all duration-200 ${
                  isActive
                    ? 'bg-primary/5 text-primary shadow-sm shadow-primary/5'
                    : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'
                }`}
              >
                <item.icon
                  className={`mr-3 h-5 w-5 transition-colors ${
                    isActive ? 'text-primary' : 'text-gray-400 group-hover:text-gray-500'
                  }`}
                />
                {item.name}
              </Link>
            );
          })}
        </nav>

        <div className="p-4 border-t border-gray-50">
          <button 
            onClick={logout} 
            className="flex items-center w-full px-4 py-3 text-sm font-semibold text-gray-500 rounded-2xl hover:bg-red-50 hover:text-red-600 transition-all duration-200"
          >
            <LogOut className="mr-3 h-5 w-5" />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Mobile Header */}
      <div className="lg:hidden fixed top-0 left-0 right-0 h-16 bg-white/80 backdrop-blur-md border-b border-gray-200 flex items-center justify-between px-4 z-30">
        <div className="flex items-center gap-2">
          <Logo className="w-8 h-8" />
          <span className="font-bold text-gray-900">SongBus</span>
        </div>
        <button 
          onClick={() => setIsMobileMenuOpen(true)}
          className="p-2 text-gray-500 hover:bg-gray-100 rounded-xl"
        >
          <Menu className="w-6 h-6" />
        </button>
      </div>

      {/* Mobile Menu Overlay */}
      {isMobileMenuOpen && (
        <div className="lg:hidden fixed inset-0 z-40">
          <div className="fixed inset-0 bg-gray-900/60 backdrop-blur-sm" onClick={closeMobileMenu} />
          <aside className="fixed top-0 right-0 bottom-0 w-80 bg-white shadow-2xl flex flex-col animate-in slide-in-from-right duration-300">
            <div className="flex items-center justify-between px-6 h-20 border-b border-gray-50">
              <span className="font-bold text-gray-900">Menu</span>
              <button onClick={closeMobileMenu} className="p-2 text-gray-400 hover:bg-gray-100 rounded-full">
                <X className="w-6 h-6" />
              </button>
            </div>
            <nav className="flex-1 px-4 py-6 space-y-2">
              {navigation.map((item) => {
                const isActive = location.pathname === item.href;
                return (
                  <Link
                    key={item.name}
                    to={item.href}
                    onClick={closeMobileMenu}
                    className={`flex items-center px-4 py-4 text-base font-bold rounded-2xl transition-all ${
                      isActive ? 'bg-primary text-white shadow-lg shadow-primary/20' : 'text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    <item.icon className="mr-4 h-6 w-6" />
                    {item.name}
                  </Link>
                );
              })}
            </nav>
            <div className="p-6 border-t border-gray-50">
              <button 
                onClick={logout} 
                className="flex items-center w-full px-6 py-4 text-base font-bold text-red-500 bg-red-50 rounded-2xl"
              >
                <LogOut className="mr-4 h-6 w-6" />
                Sign Out
              </button>
            </div>
          </aside>
        </div>
      )}

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden relative">
        <div className="flex-1 overflow-y-auto pt-20 lg:pt-0 pb-12">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <Outlet />
          </div>
        </div>
      </main>
    </div>
  );
};

export default Layout;
