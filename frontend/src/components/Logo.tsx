import React from 'react';

const Logo = ({ className = "w-12 h-12" }: { className?: string }) => {
  return (
    <div className={`${className} relative group flex items-center justify-center`}>
      <svg
        viewBox="0 0 100 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full transform transition-transform duration-500 group-hover:scale-110"
      >
        {/* Abstract Bus Body - Pastel Blue */}
        <rect
          x="15"
          y="35"
          width="70"
          height="40"
          rx="12"
          fill="#B9D7EA" 
          className="animate-bus-bounce"
        />
        
        {/* Front Window - Pastel Gray/Blue */}
        <path
          d="M65 35H73C79.6274 35 85 40.3726 85 47V55H65V35Z"
          fill="#D6E6F2"
        />

        {/* Side Windows */}
        <rect x="25" y="42" width="12" height="12" rx="4" fill="#D6E6F2" />
        <rect x="42" y="42" width="12" height="12" rx="4" fill="#D6E6F2" />

        {/* Wheels - Muted Dark Gray */}
        <circle cx="30" cy="75" r="8" fill="#4A4A4A" className="animate-wheel-spin" />
        <circle cx="70" cy="75" r="8" fill="#4A4A4A" className="animate-wheel-spin" />
        
        {/* Headlight - Soft Yellow */}
        <circle cx="82" cy="62" r="3" fill="#F7FBFC" className="animate-pulse" />

        {/* Abstract Sound Waves / Notes - Pastel Pink/Purple */}
        <path
          d="M20 25C25 20 35 20 40 25"
          stroke="#F3D1F4"
          strokeWidth="3"
          strokeLinecap="round"
          className="opacity-0 group-hover:opacity-100 transition-opacity duration-300 animate-note-float-1"
        />
        <circle cx="50" cy="15" r="2" fill="#D1D1F4" className="opacity-0 group-hover:opacity-100 transition-opacity duration-500 animate-note-float-2" />
        <path
          d="M60 20L65 15"
          stroke="#F3D1F4"
          strokeWidth="2"
          strokeLinecap="round"
          className="opacity-0 group-hover:opacity-100 transition-opacity duration-700 animate-note-float-3"
        />
      </svg>

      <style>{`
        @keyframes bus-bounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-2px); }
        }
        @keyframes wheel-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes note-float-1 {
          0% { transform: translate(0, 0) scale(1); opacity: 0.8; }
          100% { transform: translate(-5px, -15px) scale(1.2); opacity: 0; }
        }
        @keyframes note-float-2 {
          0% { transform: translate(0, 0); opacity: 0.8; }
          100% { transform: translate(10px, -20px); opacity: 0; }
        }
        @keyframes note-float-3 {
          0% { transform: translate(0, 0); opacity: 0.8; }
          100% { transform: translate(5px, -25px); opacity: 0; }
        }
        .animate-bus-bounce {
          animation: bus-bounce 2s ease-in-out infinite;
        }
        .group:hover .animate-wheel-spin {
          animation: wheel-spin 1s linear infinite;
          transform-origin: center;
        }
        .animate-note-float-1 { animation: note-float-1 2s ease-out infinite; transform-origin: 20px 25px; }
        .animate-note-float-2 { animation: note-float-2 2.5s ease-out infinite; }
        .animate-note-float-3 { animation: note-float-3 1.8s ease-out infinite; }
      `}</style>
    </div>
  );
};

export default Logo;
