import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';

export default function ProtectedRoute({ allowedRoles, redirectTo, children }) {
  const { user, role, authReady } = useAuth();
  let fallback = '/login';
  if (allowedRoles && allowedRoles.includes('admin')) fallback = '/admin/login';
  else if (allowedRoles && allowedRoles.includes('seller')) fallback = '/seller/login';
  if (redirectTo) fallback = redirectTo;

  if (!authReady) {
    return <div className="container page-section">Đang tải phiên đăng nhập...</div>;
  }

  if (!user) {
    return <Navigate to={fallback} replace />;
  }

  if (allowedRoles && !allowedRoles.includes(role)) {
    return <Navigate to={fallback} replace />;
  }

  return children;
}


