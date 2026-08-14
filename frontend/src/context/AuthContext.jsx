import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import api from '../services/api';

const AuthContext = createContext(null);

function normalizeUser(nextUser) {
  if (!nextUser) return null;
  const id = nextUser.id || nextUser.userId || nextUser._id;
  return id ? { ...nextUser, id } : nextUser;
}

function decodeTokenUser(token) {
  try {
    if (!token) return null;
    const [, payload] = token.split('.');
    if (!payload) return null;
    const normalizedPayload = payload.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(payload.length / 4) * 4, '=');
    const decoded = JSON.parse(atob(normalizedPayload));
    return normalizeUser({
      id: decoded.id,
      email: decoded.email,
      role: decoded.role,
      shopId: decoded.shopId || null,
      tokenVersion: decoded.tokenVersion
    });
  } catch {
    return null;
  }
}

function readStoredUser() {
  try {
    const raw = sessionStorage.getItem('auth_user') || localStorage.getItem('auth_user');
    return raw ? normalizeUser(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

function readStoredToken() {
  return sessionStorage.getItem('token') || localStorage.getItem('token');
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => readStoredUser() || decodeTokenUser(readStoredToken()));
  const [token, setToken] = useState(readStoredToken());
  const [authReady, setAuthReady] = useState(false);

  const login = useCallback((nextUser, nextToken) => {
    const normalizedUser = normalizeUser(nextUser);
    if (nextToken) {
      sessionStorage.setItem('token', nextToken);
      localStorage.setItem('token', nextToken);
    }
    if (nextToken) setToken(nextToken);
    if (normalizedUser) {
      sessionStorage.setItem('auth_user', JSON.stringify(normalizedUser));
      localStorage.setItem('auth_user', JSON.stringify(normalizedUser));
      setUser(normalizedUser);
    }
    setAuthReady(true);
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem('token');
    sessionStorage.removeItem('auth_user');
    localStorage.removeItem('token');
    localStorage.removeItem('auth_user');
    setToken(null);
    setUser(null);
    setAuthReady(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const storedToken = readStoredToken();
    const storedUser = readStoredUser() || decodeTokenUser(storedToken);

    if (!storedToken) {
      logout();
      return () => {
        cancelled = true;
      };
    }

    sessionStorage.setItem('token', storedToken);
    localStorage.setItem('token', storedToken);
    setToken(storedToken);

    if (storedUser?.id) {
      sessionStorage.setItem('auth_user', JSON.stringify(storedUser));
      localStorage.setItem('auth_user', JSON.stringify(storedUser));
      setUser(storedUser);
      setAuthReady(true);
      return () => {
        cancelled = true;
      };
    }

    api
      .post('/auth/session', { token: storedToken })
      .then((res) => {
        if (cancelled) return;
        const sessionUser = normalizeUser(res.data?.user);
        if (!sessionUser?.id) {
          logout();
          return;
        }
        sessionStorage.setItem('auth_user', JSON.stringify(sessionUser));
        localStorage.setItem('auth_user', JSON.stringify(sessionUser));
        setUser(sessionUser);
      })
      .catch(() => {
        if (!cancelled) logout();
      })
      .finally(() => {
        if (!cancelled) setAuthReady(true);
      });

    return () => {
      cancelled = true;
    };
  }, [logout]);

  const value = useMemo(
    () => ({
      user,
      token,
      authReady,
      role: user?.role || null,
      isBuyer: user?.role === 'buyer',
      isSeller: user?.role === 'seller',
      isAdmin: user?.role === 'admin',
      login,
      logout
    }),
    [user, token, authReady, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}


