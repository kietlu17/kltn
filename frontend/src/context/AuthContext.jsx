import { createContext, useContext, useMemo, useState } from 'react';

const AuthContext = createContext(null);

function readStoredUser() {
  try {
    const raw = sessionStorage.getItem('auth_user');
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function readStoredToken() {
  return sessionStorage.getItem('token');
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(readStoredUser());
  const [token, setToken] = useState(readStoredToken());

  const login = (nextUser, token) => {
    if (token) sessionStorage.setItem('token', token);
    localStorage.removeItem('token');
    if (token) setToken(token);
    if (nextUser) {
      sessionStorage.setItem('auth_user', JSON.stringify(nextUser));
      localStorage.removeItem('auth_user');
      setUser(nextUser);
    }
  };

  const logout = () => {
    sessionStorage.removeItem('token');
    sessionStorage.removeItem('auth_user');
    localStorage.removeItem('token');
    localStorage.removeItem('auth_user');
    setToken(null);
    setUser(null);
  };

  const value = useMemo(
    () => ({
      user,
      token,
      role: user?.role || null,
      isBuyer: user?.role === 'buyer',
      isSeller: user?.role === 'seller',
      isAdmin: user?.role === 'admin',
      login,
      logout
    }),
    [user, token]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}


