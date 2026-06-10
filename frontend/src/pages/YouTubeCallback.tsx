import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function YouTubeCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { token } = useAuth();
  const [status, setStatus] = useState('Connecting to YouTube Music...');

  useEffect(() => {
    const code = searchParams.get('code');
    const error = searchParams.get('error');

    if (error) {
      setStatus('Failed to connect YouTube: ' + error);
      setTimeout(() => navigate('/settings'), 3000);
      return;
    }

    if (code && token) {
      fetch('/api/integrations/youtube/callback', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ code })
      })
      .then(res => {
        if (!res.ok) throw new Error('Failed to exchange Google code');
        return res.json();
      })
      .then(() => {
        setStatus('Successfully connected YouTube Music!');
        setTimeout(() => navigate('/settings'), 2000);
      })
      .catch(err => {
        setStatus(err.message);
        setTimeout(() => navigate('/settings'), 3000);
      });
    } else if (!token) {
        setStatus('You must be logged in to connect YouTube.');
        setTimeout(() => navigate('/login'), 2000);
    }
  }, [searchParams, token, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="max-w-md w-full bg-white p-8 rounded-lg shadow text-center">
        <h2 className="text-xl font-semibold text-gray-900">{status}</h2>
      </div>
    </div>
  );
}
